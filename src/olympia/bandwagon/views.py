import functools
import hashlib
import os

from django import http
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext, ugettext_lazy as _lazy
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from django_statsd.clients import statsd
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.views import AccountViewSet
from olympia.addons.models import Addon
from olympia.addons.views import BaseFilter
from olympia.amo import messages
from olympia.amo.decorators import (
    allow_mine, json_view, login_required, post_required, use_primary_db)
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import paginate, render, urlparams
from olympia.api.filters import OrderingAliasFilter
from olympia.api.permissions import (
    AllOf, AllowReadOnlyIfPublic, AnyOf, PreventActionPermission)
from olympia.legacy_api.utils import addon_to_dict
from olympia.tags.models import Tag
from olympia.translations.query import order_by_translation
from olympia.users.models import UserProfile

from . import forms, tasks
from .models import SPECIAL_SLUGS, Collection, CollectionAddon
from .permissions import (
    AllowCollectionAuthor, AllowCollectionContributor, AllowContentCurators)
from .serializers import (
    CollectionAddonSerializer, CollectionSerializer,
    CollectionWithAddonsSerializer)


log = olympia.core.logger.getLogger('z.collections')


@non_atomic_requests
def get_collection(request, username, slug):
    if (slug in SPECIAL_SLUGS.values() and request.user.is_authenticated() and
            request.user.username == username):
        return getattr(request.user, slug + '_collection')()
    else:
        return get_object_or_404(Collection.objects,
                                 author__username=username, slug=slug)


def owner_required(f=None, require_owner=True):
    """Requires collection to be owned, by someone."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, username, slug, *args, **kw):
            collection = get_collection(request, username, slug)
            if acl.check_collection_ownership(request, collection,
                                              require_owner=require_owner):
                return func(request, collection, username, slug, *args, **kw)
            else:
                raise PermissionDenied
        return wrapper
    return decorator(f) if f else decorator


@non_atomic_requests
def legacy_redirect(request, uuid, edit=False):
    # Nicknames have a limit of 30, so len == 36 implies a uuid.
    key = 'uuid' if len(uuid) == 36 else 'nickname'
    collection = get_object_or_404(Collection.objects, **{key: uuid})
    if edit:
        return http.HttpResponseRedirect(collection.edit_url())

    to = collection.get_url_path()
    params = request.GET.urlencode()

    if params:
        to += '?' + params

    return http.HttpResponseRedirect(to)


@non_atomic_requests
def legacy_directory_redirects(request, page):
    sorts = {'editors_picks': 'featured', 'popular': 'popular'}
    loc = base = reverse('collections.list')
    if page in sorts:
        loc = urlparams(base, sort=sorts[page])
    elif request.user.is_authenticated():
        if page == 'mine':
            loc = reverse('collections.user', args=[request.user.username])
    return http.HttpResponseRedirect(loc)


@non_atomic_requests
def render_cat(request, template, data=None, extra=None):
    if extra is None:
        extra = {}
    if data is None:
        data = {}
    data.update(dict(search_cat='collections'))
    return render(request, template, data, **extra)


@non_atomic_requests
def collection_listing(request, base=None):
    qs = (
        Collection.objects.listed()
                  .filter(Q(application=request.APP.id) | Q(application=None))
                  .filter(type=amo.COLLECTION_FEATURED)
                  .exclude(addon_count=0)
    )
    # Counts are hard to cache automatically, and accuracy for this
    # one is less important. Remember it for 5 minutes.
    countkey = hashlib.sha256(str(qs.query) + '_count').hexdigest()
    count = cache.get(countkey)
    if count is None:
        count = qs.count()
        cache.set(countkey, count, 300)
    collections = paginate(request, qs, count=count)
    return render_cat(request, 'bandwagon/impala/collection_listing.html',
                      {'collections': collections, 'src': 'co-hc-sidebar',
                       'dl_src': 'co-dp-sidebar'})


@allow_mine
@non_atomic_requests
def user_listing(request, username):
    author = get_object_or_404(UserProfile, username=username)
    qs = (Collection.objects.filter(author__username=username)
          .order_by('-created'))
    mine = (request.user.is_authenticated() and
            request.user.username == username)
    if mine:
        page = 'mine'
    else:
        page = 'user'
        qs = qs.filter(listed=True)
    collections = paginate(request, qs)
    return render_cat(request, 'bandwagon/user_listing.html',
                      {'collections': collections,
                       'page': page, 'author': author})


class CollectionAddonFilter(BaseFilter):
    opts = (('added', _lazy(u'Added')),
            ('popular', _lazy(u'Popularity')),
            ('name', _lazy(u'Name')))

    def filter_added(self):
        return self.base_queryset.order_by('collectionaddon__created')

    def filter_name(self):
        return order_by_translation(self.base_queryset, 'name')

    def filter_popular(self):
        return self.base_queryset.order_by('-weekly_downloads')


@allow_mine
@non_atomic_requests
def collection_detail(request, username, slug):
    collection = get_collection(request, username, slug)
    if not collection.listed:
        if not request.user.is_authenticated():
            return redirect_for_login(request)
        if not acl.check_collection_ownership(request, collection):
            raise PermissionDenied

    base = Addon.objects.valid() & collection.addons.all()
    filter = CollectionAddonFilter(request, base,
                                   key='sort', default='popular')
    notes = get_notes(collection)
    # Go directly to CollectionAddon for the count to avoid joins.
    count = CollectionAddon.objects.filter(
        Addon.objects.all().valid_q(
            amo.VALID_ADDON_STATUSES, prefix='addon__'),
        collection=collection.id)
    addons = paginate(request, filter.qs, per_page=15, count=count.count())

    # `perms` is defined in django.contrib.auth.context_processors. Gotcha!
    user_perms = {
        'view_stats': acl.check_ownership(
            request, collection, require_owner=False),
    }

    tags = Tag.objects.filter(
        id__in=collection.top_tags) if collection.top_tags else []
    return render_cat(request, 'bandwagon/collection_detail.html',
                      {'collection': collection, 'filter': filter,
                       'addons': addons, 'notes': notes,
                       'tags': tags, 'user_perms': user_perms})


@json_view(has_trans=True)
@allow_mine
@non_atomic_requests
def collection_detail_json(request, username, slug):
    collection = get_collection(request, username, slug)
    if not (collection.listed or acl.check_collection_ownership(
            request, collection)):
        raise PermissionDenied
    # We evaluate the QuerySet with `list` to work around bug 866454.
    addons_dict = [addon_to_dict(a) for a in list(collection.addons.valid())]
    return {
        'name': collection.name,
        'url': collection.get_abs_url(),
        'iconUrl': collection.icon_url,
        'addons': addons_dict
    }


def get_notes(collection, raw=False):
    # This might hurt in a big collection with lots of notes.
    # It's a generator so we don't evaluate anything by default.
    notes = CollectionAddon.objects.filter(collection=collection,
                                           comments__isnull=False)
    rv = {}
    for note in notes:
        # Watch out for comments in a language we didn't pick up.
        if note.comments:
            rv[note.addon_id] = (note.comments.localized_string if raw
                                 else note.comments)
    yield rv


def initial_data_from_request(request):
    return {'author': request.user, 'application': request.APP.id}


def collection_message(request, collection, option):
    if option == 'add':
        title = ugettext('Collection created!')
        msg = ugettext(
            'Your new collection is shown below. You can '
            '<a href="%(url)s">edit additional settings</a> if you\'d '
            'like.'
        ) % {'url': collection.edit_url()}
    elif option == 'update':
        title = ugettext('Collection updated!')
        msg = ugettext(
            '<a href="%(url)s">View your collection</a> to see the changes.'
        ) % {'url': collection.get_url_path()}
    else:
        raise ValueError('Incorrect option "%s", '
                         'takes only "add" or "update".' % option)
    messages.success(request, title, msg, message_safe=True)


@use_primary_db
@login_required
def add(request):
    """Displays/processes a form to create a collection."""
    ctx = {}
    if request.method == 'POST':
        form = forms.CollectionForm(
            request.POST, request.FILES,
            initial=initial_data_from_request(request))
        aform = forms.AddonsForm(request.POST)
        if form.is_valid():
            collection = form.save(default_locale=request.LANG)
            collection.save()
            if aform.is_valid():
                aform.save(collection)
            collection_message(request, collection, 'add')
            statsd.incr('collections.created')
            log.info('Created collection %s' % collection.id)
            return http.HttpResponseRedirect(collection.get_url_path())
        else:
            ctx['addons'] = Addon.objects.filter(pk__in=aform.clean_addon())
            ctx['comments'] = aform.clean_addon_comment()
    else:
        form = forms.CollectionForm()

    ctx['form'] = form
    return render_cat(request, 'bandwagon/add.html', ctx)


@use_primary_db
@login_required(redirect=False)
def ajax_new(request):
    form = forms.CollectionForm(
        request.POST or None,
        initial=initial_data_from_request(request))

    if request.method == 'POST' and form.is_valid():
        collection = form.save()
        addon_id = request.POST['addon_id']

        collection.add_addon(Addon.objects.get(pk=addon_id))
        log.info('Created collection %s' % collection.id)
        return http.HttpResponseRedirect(reverse('collections.ajax_list') +
                                         '?addon_id=%s' % addon_id)

    return render(request, 'bandwagon/ajax_new.html', {'form': form})


@login_required(redirect=False)
@non_atomic_requests
def ajax_list(request):
    try:
        addon_id = int(request.GET['addon_id'])
    except (KeyError, ValueError):
        return http.HttpResponseBadRequest()

    qs = Collection.objects.owned_by(request.user).with_has_addon(addon_id)

    return render(request, 'bandwagon/ajax_list.html',
                  {'collections': order_by_translation(qs, 'name')})


@use_primary_db
@login_required
@post_required
def collection_alter(request, username, slug, action):
    collection = get_collection(request, username, slug)
    return change_addon(request, collection, action)


def change_addon(request, collection, action):
    if not acl.check_collection_ownership(request, collection):
        raise PermissionDenied

    try:
        addon = get_object_or_404(Addon.objects, pk=request.POST['addon_id'])
    except (ValueError, KeyError):
        return http.HttpResponseBadRequest()

    getattr(collection, action + '_addon')(addon)
    log.info(u'%s: %s %s to collection %s' %
             (request.user, action, addon.id, collection.id))

    if request.is_ajax():
        url = '%s?addon_id=%s' % (reverse('collections.ajax_list'), addon.id)
    else:
        url = collection.get_url_path()
    return http.HttpResponseRedirect(url)


@use_primary_db
@login_required
@post_required
def ajax_collection_alter(request, action):
    try:
        collection = get_object_or_404(
            Collection.objects, pk=request.POST['id'])
    except (ValueError, KeyError):
        return http.HttpResponseBadRequest()
    return change_addon(request, collection, action)


@use_primary_db
@login_required
# Contributors are allowed to *see* the page, but there is another
# permission check below to prevent them from doing any modifications.
@owner_required(require_owner=False)
def edit(request, collection, username, slug):
    is_admin = acl.action_allowed(request, amo.permissions.ADMIN_CURATION)

    if not acl.check_collection_ownership(
            request, collection, require_owner=True):
        if request.method == 'POST':
            raise PermissionDenied
        form = None
    elif request.method == 'POST':
        initial = initial_data_from_request(request)
        if collection.author_id:  # Don't try to change the author.
            initial['author'] = collection.author
        form = forms.CollectionForm(request.POST, request.FILES,
                                    initial=initial,
                                    instance=collection)
        if form.is_valid():
            collection = form.save()
            collection_message(request, collection, 'update')
            log.info(u'%s edited collection %s' %
                     (request.user, collection.id))
            return http.HttpResponseRedirect(collection.edit_url())
    else:
        form = forms.CollectionForm(instance=collection)

    qs = (CollectionAddon.objects.using('default')
          .filter(collection=collection))
    meta = {c.addon_id: c for c in qs}
    addons = collection.addons.all()
    comments = next(get_notes(collection, raw=True))

    data = {
        'collection': collection,
        'form': form,
        'username': username,
        'slug': slug,
        'meta': meta,
        'is_admin': is_admin,
        'addons': addons,
        'comments': comments
    }
    return render_cat(request, 'bandwagon/edit.html', data)


@use_primary_db
@login_required
@owner_required(require_owner=False)
@post_required
def edit_addons(request, collection, username, slug):
    if request.method == 'POST':
        form = forms.AddonsForm(request.POST)
        if form.is_valid():
            form.save(collection)
            collection_message(request, collection, 'update')
            log.info(u'%s added add-ons to %s' %
                     (request.user, collection.id))

    return http.HttpResponseRedirect(collection.edit_url() + '#addons-edit')


@use_primary_db
@login_required
@owner_required
@post_required
def edit_privacy(request, collection, username, slug):
    collection.listed = not collection.listed
    collection.save()
    log.info(u'%s changed privacy on collection %s' %
             (request.user, collection.id))
    return http.HttpResponseRedirect(collection.get_url_path())


@use_primary_db
@login_required
def delete(request, username, slug):
    collection = get_object_or_404(Collection, author__username=username,
                                   slug=slug)

    if not acl.check_collection_ownership(request, collection, True):
        log.info(u'%s is trying to delete collection %s'
                 % (request.user, collection.id))
        raise PermissionDenied

    data = dict(collection=collection, username=username, slug=slug)

    if request.method == 'POST':
        if request.POST['sure'] == '1':
            collection.delete()
            log.info(u'%s deleted collection %s' %
                     (request.user, collection.id))
            url = reverse('collections.user', args=[username])
            return http.HttpResponseRedirect(url)
        else:
            return http.HttpResponseRedirect(collection.get_url_path())

    return render_cat(request, 'bandwagon/delete.html', data)


@require_POST
@use_primary_db
@login_required
@owner_required
@json_view
@csrf_protect
def delete_icon(request, collection, username, slug):
    log.debug(u"User deleted collection (%s) icon " % slug)
    tasks.delete_icon(os.path.join(collection.get_img_dir(),
                                   '%d.png' % collection.id))

    collection.icontype = ''
    collection.save()

    if request.is_ajax():
        return {'icon': collection.icon_url}
    else:
        messages.success(request, ugettext('Icon Deleted'))
        return http.HttpResponseRedirect(collection.edit_url())


@login_required
@allow_mine
@non_atomic_requests
def mine(request, username=None, slug=None):
    if slug is None:
        return user_listing(request, username)
    else:
        return collection_detail(request, username, slug)


class CollectionViewSet(ModelViewSet):
    permission_classes = [
        AnyOf(
            # Collection authors can do everything.
            AllowCollectionAuthor,
            # Collection contributors can access the featured themes collection
            # (it's community-managed) and change it's addons, but can't delete
            # or edit it's details.
            AllOf(AllowCollectionContributor,
                  PreventActionPermission(('create', 'list', 'update',
                                           'destroy', 'partial_update'))),
            # Content curators can modify existing mozilla collections as they
            # see fit, but can't list or delete them.
            AllOf(AllowContentCurators,
                  PreventActionPermission(('create', 'destroy', 'list'))),
            # Everyone else can do read-only stuff, except list.
            AllOf(AllowReadOnlyIfPublic,
                  PreventActionPermission('list'))),
    ]
    lookup_field = 'slug'

    def get_account_viewset(self):
        if not hasattr(self, 'account_viewset'):
            self.account_viewset = AccountViewSet(
                request=self.request,
                permission_classes=[],  # We handled permissions already.
                kwargs={'pk': self.kwargs['user_pk']})
        return self.account_viewset

    def get_serializer_class(self):
        with_addons = ('with_addons' in self.request.GET and
                       self.action == 'retrieve')
        return (CollectionSerializer if not with_addons
                else CollectionWithAddonsSerializer)

    def get_queryset(self):
        return Collection.objects.filter(
            author=self.get_account_viewset().get_object()).order_by(
            '-modified')

    def get_addons_queryset(self):
        collection_addons_viewset = CollectionAddonViewSet(
            request=self.request
        )
        # Set this to avoid a pointless lookup loop.
        collection_addons_viewset.collection_viewset = self
        # This needs to be list to make the filtering work.
        collection_addons_viewset.action = 'list'
        qs = collection_addons_viewset.get_queryset()
        # Now limit and sort
        limit = settings.REST_FRAMEWORK['PAGE_SIZE']
        sort = collection_addons_viewset.ordering[0]
        return qs.order_by(sort)[:limit]


class TranslationAwareOrderingAliasFilter(OrderingAliasFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)

        if len(ordering) > 1:
            # We can't support multiple orderings easily because of
            # how order_by_translation works.
            raise serializers.ValidationError(
                'You can only specify one "sort" argument. Multiple '
                'orderings are not supported')

        order_by = ordering[0]

        if order_by in ('name', '-name'):
            return order_by_translation(queryset, order_by, Addon)

        sup = super(TranslationAwareOrderingAliasFilter, self)
        return sup.filter_queryset(request, queryset, view)


class CollectionAddonViewSet(ModelViewSet):
    permission_classes = []  # We don't need extra permissions.
    serializer_class = CollectionAddonSerializer
    lookup_field = 'addon'
    filter_backends = (TranslationAwareOrderingAliasFilter,)
    ordering_fields = ()
    ordering_field_aliases = {'popularity': 'addon__weekly_downloads',
                              'name': 'name',
                              'added': 'created'}
    ordering = ('-addon__weekly_downloads',)

    def get_collection_viewset(self):
        if not hasattr(self, 'collection_viewset'):
            # CollectionViewSet's permission_classes are good for us.
            self.collection_viewset = CollectionViewSet(
                request=self.request,
                kwargs={'user_pk': self.kwargs['user_pk'],
                        'slug': self.kwargs['collection_slug']})
        return self.collection_viewset

    def get_object(self):
        self.lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(self.lookup_url_kwarg)
        # if the lookup is not a number, its probably the slug instead.
        if lookup_value and not unicode(lookup_value).isdigit():
            self.lookup_field = '%s__slug' % self.lookup_field
        return super(CollectionAddonViewSet, self).get_object()

    def get_queryset(self):
        qs = (
            CollectionAddon.objects
            .filter(collection=self.get_collection_viewset().get_object())
            .prefetch_related('addon'))

        filter_param = self.request.GET.get('filter')
        # We only filter list action.
        include_all_with_deleted = (filter_param == 'all_with_deleted' or
                                    self.action != 'list')
        # If deleted addons are requested, that implies all addons.
        include_all = filter_param == 'all' or include_all_with_deleted

        if not include_all:
            qs = qs.filter(
                addon__status=amo.STATUS_PUBLIC, addon__disabled_by_user=False)
        elif not include_all_with_deleted:
            qs = qs.exclude(addon__status=amo.STATUS_DELETED)
        return qs
