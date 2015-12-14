import functools
import hashlib
import os

from django import http
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect

import caching.base as caching
import commonware.log
from tower import ugettext_lazy as _lazy, ugettext as _
from django_statsd.clients import statsd

import amo
from amo import messages
import sharing.views
from amo.decorators import (allow_mine, json_view, login_required,
                            post_required, restricted_content, write)
from amo.urlresolvers import reverse
from amo.utils import paginate, redirect_for_login, urlparams
from access import acl
from addons.models import Addon
from addons.views import BaseFilter
from api.utils import addon_to_dict
from tags.models import Tag
from translations.query import order_by_translation
from users.models import UserProfile
from .models import (Collection, CollectionAddon, CollectionWatcher,
                     CollectionVote, SPECIAL_SLUGS)
from . import forms, tasks

log = commonware.log.getLogger('z.collections')


def get_collection(request, username, slug):
    if (slug in SPECIAL_SLUGS.values() and request.user.is_authenticated()
            and request.user.username == username):
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


def legacy_redirect(request, uuid, edit=False):
    # Nicknames have a limit of 30, so len == 36 implies a uuid.
    key = 'uuid' if len(uuid) == 36 else 'nickname'
    c = get_object_or_404(Collection.objects, **{key: uuid})
    if edit:
        return http.HttpResponseRedirect(c.edit_url())
    to = c.get_url_path() + '?' + request.GET.urlencode()
    return http.HttpResponseRedirect(to)


def legacy_directory_redirects(request, page):
    sorts = {'editors_picks': 'featured', 'popular': 'popular',
             'users': 'followers'}
    loc = base = reverse('collections.list')
    if page in sorts:
        loc = urlparams(base, sort=sorts[page])
    elif request.user.is_authenticated():
        if page == 'mine':
            loc = reverse('collections.user', args=[request.user.username])
        elif page == 'favorites':
            loc = reverse('collections.following')
    return http.HttpResponseRedirect(loc)


class CollectionFilter(BaseFilter):
    opts = (('featured', _lazy(u'Featured')),
            ('followers', _lazy(u'Most Followers')),
            ('created', _lazy(u'Newest')))
    extras = (('name', _lazy(u'Name')),
              ('updated', _lazy(u'Recently Updated')),
              ('popular', _lazy(u'Recently Popular')))

    def filter_featured(self):
        return self.base_queryset.filter(type=amo.COLLECTION_FEATURED)

    def filter_followers(self):
        return self.base_queryset.order_by('-subscribers')

    def filter_popular(self):
        return self.base_queryset.order_by('-weekly_subscribers')

    def filter_updated(self):
        return self.base_queryset.order_by('-modified')

    def filter_created(self):
        return self.base_queryset.order_by('-created')

    def filter_name(self):
        return order_by_translation(self.base_queryset, 'name')


def get_filter(request, base=None):
    if base is None:
        base = Collection.objects.listed()
    base = (base.filter(Q(application=request.APP.id) | Q(application=None))
            .exclude(addon_count=0))
    return CollectionFilter(request, base, key='sort', default='featured')


def render_cat(request, template, data={}, extra={}):
    data.update(dict(search_cat='collections'))
    return render(request, template, data, **extra)


# TODO (potch): restore this when we do mobile bandwagon
# @mobile_template('bandwagon/{mobile/}collection_listing.html')
def collection_listing(request, base=None):
    sort = request.GET.get('sort')
    # We turn users into followers.
    if sort == 'users':
        return redirect(urlparams(reverse('collections.list'),
                                  sort='followers'), permanent=True)
    filter = get_filter(request, base)
    # Counts are hard to cache automatically, and accuracy for this
    # one is less important. Remember it for 5 minutes.
    countkey = hashlib.md5(str(filter.qs.query) + '_count').hexdigest()
    count = cache.get(countkey)
    if count is None:
        count = filter.qs.count()
        cache.set(countkey, count, 300)
    collections = paginate(request, filter.qs, count=count)
    return render_cat(request, 'bandwagon/impala/collection_listing.html',
                      dict(collections=collections, src='co-hc-sidebar',
                           dl_src='co-dp-sidebar', filter=filter, sort=sort,
                           sorting=filter.field))


def get_votes(request, collections):
    if not request.user.is_authenticated():
        return {}
    q = CollectionVote.objects.filter(
        user=request.user, collection__in=[c.id for c in collections])
    return dict((v.collection_id, v) for v in q)


@allow_mine
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
    votes = get_votes(request, collections.object_list)
    return render_cat(request, 'bandwagon/user_listing.html',
                      dict(collections=collections, collection_votes=votes,
                           page=page, author=author,
                           filter=get_filter(request)))


class CollectionAddonFilter(BaseFilter):
    opts = (('added', _lazy(u'Added')),
            ('popular', _lazy(u'Popularity')),
            ('name', _lazy(u'Name')))

    def filter_added(self):
        return self.base_queryset.order_by('collectionaddon__created')

    def filter_name(self):
        return order_by_translation(self.base_queryset, 'name')

    def filter_popular(self):
        return (self.base_queryset.order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))


@allow_mine
def collection_detail(request, username, slug):
    c = get_collection(request, username, slug)
    if not c.listed:
        if not request.user.is_authenticated():
            return redirect_for_login(request)
        if not acl.check_collection_ownership(request, c):
            raise PermissionDenied

    if request.GET.get('format') == 'rss':
        return http.HttpResponsePermanentRedirect(c.feed_url())

    base = Addon.objects.valid() & c.addons.all()
    filter = CollectionAddonFilter(request, base,
                                   key='sort', default='popular')
    notes = get_notes(c)
    # Go directly to CollectionAddon for the count to avoid joins.
    count = CollectionAddon.objects.filter(
        Addon.objects.valid_q(amo.VALID_STATUSES, prefix='addon__'),
        collection=c.id)
    addons = paginate(request, filter.qs, per_page=15, count=count.count())

    # The add-on query is not related to the collection, so we need to manually
    # hook them up for invalidation.  Bonus: count invalidation.
    keys = [addons.object_list.flush_key(), count.flush_key()]
    caching.invalidator.add_to_flush_list({c.flush_key(): keys})

    if c.author_id:
        qs = Collection.objects.listed().filter(author=c.author)
        others = amo.utils.randslice(qs, limit=4, exclude=c.id)
    else:
        others = []

    # `perms` is defined in django.contrib.auth.context_processors. Gotcha!
    user_perms = {
        'view_stats': acl.check_ownership(request, c, require_owner=False),
    }

    tags = Tag.objects.filter(id__in=c.top_tags) if c.top_tags else []
    return render_cat(request, 'bandwagon/collection_detail.html',
                      {'collection': c, 'filter': filter, 'addons': addons,
                       'notes': notes, 'author_collections': others,
                       'tags': tags, 'user_perms': user_perms})


@json_view(has_trans=True)
@allow_mine
def collection_detail_json(request, username, slug):
    c = get_collection(request, username, slug)
    if not (c.listed or acl.check_collection_ownership(request, c)):
        raise PermissionDenied
    # We evaluate the QuerySet with `list` to work around bug 866454.
    addons_dict = [addon_to_dict(a) for a in list(c.addons.valid())]
    return {
        'name': c.name,
        'url': c.get_abs_url(),
        'iconUrl': c.icon_url,
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


@write
@login_required
def collection_vote(request, username, slug, direction):
    c = get_collection(request, username, slug)
    if request.method != 'POST':
        return http.HttpResponseRedirect(c.get_url_path())

    vote = {'up': 1, 'down': -1}[direction]
    qs = (CollectionVote.objects.using('default')
          .filter(collection=c, user=request.user))

    if qs:
        cv = qs[0]
        if vote == cv.vote:  # Double vote => cancel.
            cv.delete()
        else:
            cv.vote = vote
            cv.save(force_update=True)
    else:
        CollectionVote.objects.create(collection=c, user=request.user,
                                      vote=vote)

    if request.is_ajax():
        return http.HttpResponse()
    else:
        return http.HttpResponseRedirect(c.get_url_path())


def initial_data_from_request(request):
    return dict(author=request.user, application=request.APP.id)


def collection_message(request, collection, option):
    if option == 'add':
        title = _('Collection created!')
        msg = _("""Your new collection is shown below. You can <a
                   href="%(url)s">edit additional settings</a> if you'd
                   like.""") % {'url': collection.edit_url()}
    elif option == 'update':
        title = _('Collection updated!')
        msg = _("""<a href="%(url)s">View your collection</a> to see the
                   changes.""") % {'url': collection.get_url_path()}
    else:
        raise ValueError('Incorrect option "%s", '
                         'takes only "add" or "update".' % option)
    messages.success(request, title, msg, message_safe=True)


@write
@login_required
@restricted_content
def add(request):
    """Displays/processes a form to create a collection."""
    data = {}
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
            data['addons'] = Addon.objects.filter(pk__in=aform.clean_addon())
            data['comments'] = aform.clean_addon_comment()
    else:
        form = forms.CollectionForm()

    data.update(form=form, filter=get_filter(request))
    return render_cat(request, 'bandwagon/add.html', data)


@write
@login_required(redirect=False)
def ajax_new(request):
    form = forms.CollectionForm(
        request.POST or None,
        initial={'author': request.user, 'application': request.APP.id},
    )

    if request.method == 'POST' and form.is_valid():
        collection = form.save()
        addon_id = request.REQUEST['addon_id']
        collection.add_addon(Addon.objects.get(pk=addon_id))
        log.info('Created collection %s' % collection.id)
        return http.HttpResponseRedirect(reverse('collections.ajax_list')
                                         + '?addon_id=%s' % addon_id)

    return render(request, 'bandwagon/ajax_new.html', {'form': form})


@login_required(redirect=False)
def ajax_list(request):
    try:
        addon_id = int(request.GET['addon_id'])
    except (KeyError, ValueError):
        return http.HttpResponseBadRequest()

    collections = (
        Collection.objects
        .publishable_by(request.user)
        .with_has_addon(addon_id))

    return render(request, 'bandwagon/ajax_list.html',
                  {'collections': collections})


@write
@login_required
@post_required
def collection_alter(request, username, slug, action):
    c = get_collection(request, username, slug)
    return change_addon(request, c, action)


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


@write
@login_required
@post_required
def ajax_collection_alter(request, action):
    try:
        c = get_object_or_404(Collection.objects, pk=request.POST['id'])
    except (ValueError, KeyError):
        return http.HttpResponseBadRequest()
    return change_addon(request, c, action)


@write
@login_required
@owner_required(require_owner=False)
def edit(request, collection, username, slug):
    is_admin = acl.action_allowed(request, 'Collections', 'Edit')

    if request.method == 'POST':
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

    qs = (CollectionAddon.objects.no_cache().using('default')
          .filter(collection=collection))
    meta = dict((c.addon_id, c) for c in qs)
    addons = collection.addons.no_cache().all()
    comments = get_notes(collection, raw=True).next()

    if is_admin:
        initial = dict(type=collection.type,
                       application=collection.application)
        admin_form = forms.AdminForm(initial=initial)
    else:
        admin_form = None

    data = dict(collection=collection,
                form=form,
                username=username,
                slug=slug,
                meta=meta,
                filter=get_filter(request),
                is_admin=is_admin,
                admin_form=admin_form,
                addons=addons,
                comments=comments)
    return render_cat(request, 'bandwagon/edit.html', data)


@write
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


@write
@login_required
@owner_required
@post_required
def edit_contributors(request, collection, username, slug):
    is_admin = acl.action_allowed(request, 'Collections', 'Edit')

    if is_admin:
        admin_form = forms.AdminForm(request.POST)
        if admin_form.is_valid():
            admin_form.save(collection)

    form = forms.ContributorsForm(request.POST)

    if form.is_valid():
        form.save(collection)
        collection_message(request, collection, 'update')
        if form.cleaned_data['new_owner']:
            return http.HttpResponseRedirect(collection.get_url_path())

    return http.HttpResponseRedirect(collection.edit_url() + '#users-edit')


@write
@login_required
@owner_required
@post_required
def edit_privacy(request, collection, username, slug):
    collection.listed = not collection.listed
    collection.save()
    log.info(u'%s changed privacy on collection %s' %
             (request.user, collection.id))
    return http.HttpResponseRedirect(collection.get_url_path())


@write
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
@write
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
        messages.success(request, _('Icon Deleted'))
        return http.HttpResponseRedirect(collection.edit_url())


@login_required
@post_required
@json_view
def watch(request, username, slug):
    """
    POST /collections/:user/:slug/watch to toggle the user's watching status.

    For ajax, return {watching: true|false}. (reflects the new value)
    Otherwise, redirect to the collection page.
    """
    collection = get_collection(request, username, slug)
    d = dict(user=request.user, collection=collection)
    qs = CollectionWatcher.objects.no_cache().using('default').filter(**d)
    watching = not qs  # Flip the bool since we're about to change it.
    if qs:
        qs.delete()
    else:
        CollectionWatcher.objects.create(**d)

    if request.is_ajax():
        return {'watching': watching}
    else:
        return http.HttpResponseRedirect(collection.get_url_path())


def share(request, username, slug):
    collection = get_collection(request, username, slug)
    return sharing.views.share(request, collection,
                               name=collection.name,
                               description=collection.description)


@login_required
def following(request):
    qs = (Collection.objects.filter(following__user=request.user)
          .order_by('-following__created'))
    collections = paginate(request, qs)
    votes = get_votes(request, collections.object_list)
    return render_cat(request, 'bandwagon/user_listing.html',
                      dict(collections=collections, votes=votes,
                           page='following', filter=get_filter(request)))


@login_required
@allow_mine
def mine(request, username=None, slug=None):
    if slug is None:
        return user_listing(request, username)
    else:
        return collection_detail(request, username, slug)
