import functools

from django import http
from django.db.models import Q
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

import jingo
from tower import ugettext_lazy as _lazy, ugettext as _

import amo.utils
from amo.decorators import login_required
from amo.urlresolvers import reverse
from access import acl
from amo.decorators import login_required
from amo.urlresolvers import reverse
from addons.models import Addon
from addons.views import BaseFilter
from tags.models import Tag
from translations.query import order_by_translation
from .models import Collection, CollectionAddon, CollectionUser, CollectionVote
from . import forms


def owner_required(f=None, require_owner=True):
    """Requires collection to be owner, by someone."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, username, slug, *args, **kw):
            collection = get_object_or_404(Collection,
                                           author__nickname=username,
                                           slug=slug)

            if acl.check_collection_ownership(request, collection,
                                              require_owner=require_owner):
                return func(request, collection, username, slug, *args, **kw)
            else:
                return http.HttpResponseForbidden(
                        _("This is not the collection you are looking for."))
        return wrapper

    if f:
        return decorator(f)
    else:
        return decorator


def legacy_redirect(request, uuid):
    # Nicknames have a limit of 30, so len == 36 implies a uuid.
    key = 'uuid' if len(uuid) == 36 else 'nickname'
    c = get_object_or_404(Collection.objects, **{key: uuid})
    return redirect(c.get_url_path())


def legacy_directory_redirects(request, page):
    sorts = {'editors_picks': 'featured', 'popular': 'popular'}
    loc = base = reverse('collections.list')
    if page in sorts:
        loc = amo.utils.urlparams(base, sort=sorts[page])
    elif request.user.is_authenticated():
        if page == 'mine':
            loc = reverse('collections.user', args=[request.amo_user.nickname])
        elif page == 'favorites':
            loc = reverse('collections.detail',
                          args=[request.amo_user.nickname, 'favorites'])
    return redirect(loc)


class CollectionFilter(BaseFilter):
    opts = (('featured', _lazy('Featured')),
            ('popular', _lazy('Popular')),
            ('rating', _lazy('Highest Rated')),
            ('created', _lazy('Recently Added')))

    def filter(self, field):
        qs = self.base_queryset
        if field == 'featured':
            return qs.filter(type=amo.COLLECTION_FEATURED)
        elif field == 'followers':
            return qs.order_by('-weekly_subscribers')
        elif field == 'rating':
            return qs.order_by('-rating')
        else:
            return qs.order_by('-created')


def collection_listing(request):
    app = Q(application=request.APP.id) | Q(application=None)
    base = Collection.objects.listed().filter(app)
    filter = CollectionFilter(request, base, key='sort', default='popular')
    collections = amo.utils.paginate(request, filter.qs)
    votes = get_votes(request, collections.object_list)
    return jingo.render(request, 'bandwagon/collection_listing.html',
                        {'collections': collections, 'filter': filter,
                         'collection_votes': votes})


def get_votes(request, collections):
    if not request.user.is_authenticated():
        return {}
    q = CollectionVote.objects.filter(
        user=request.amo_user, collection__in=[c.id for c in collections])
    return dict((v.collection_id, v) for v in q)


def user_listing(request, username):
    return http.HttpResponse()


class CollectionAddonFilter(BaseFilter):
    opts = (('added', _lazy('Added')),
            ('popular', _lazy('Popularity')),
            ('name', _lazy('Name')))

    def filter(self, field):
        if field == 'added':
            return self.base_queryset.order_by('collectionaddon__created')
        elif field == 'name':
            return order_by_translation(self.base_queryset, 'name')
        elif field == 'popular':
            return (self.base_queryset.order_by('-weekly_downloads')
                    .with_index(addons='downloads_type_idx'))


def collection_detail(request, username, slug):
    c = get_object_or_404(Collection.objects,
                          author__nickname=username, slug=slug)
    base = c.addons.all() & Addon.objects.listed(request.APP)
    filter = CollectionAddonFilter(request, base,
                                   key='sort', default='popular')
    notes = get_notes(c)
    count = CollectionAddon.objects.filter(
        Addon.objects.valid_q(prefix='addon__'), collection=c.id).count()
    addons = amo.utils.paginate(request, filter.qs, per_page=15, count=count)

    if c.author_id:
        qs = Collection.objects.listed().filter(author=c.author)
        others = amo.utils.randslice(qs, limit=4, exclude=c.id)
    else:
        others = []

    perms = {
        'view_stats': acl.check_ownership(request, c, require_owner=False),
    }

    tag_ids = c.top_tags
    tags = Tag.objects.filter(id__in=tag_ids) if tag_ids else []
    return jingo.render(request, 'bandwagon/collection_detail.html',
                        {'collection': c, 'filter': filter,
                         'addons': addons, 'notes': notes,
                         'author_collections': others, 'tags': tags,
                         'perms': perms})


def get_notes(collection):
    # This might hurt in a big collection with lots of notes.
    # It's a generator so we don't evaluate anything by default.
    notes = CollectionAddon.objects.filter(collection=collection,
                                           comments__isnull=False)
    rv = {}
    for note in notes:
        rv[note.addon_id] = note.comments
    yield rv


@login_required
def collection_vote(request, username, slug, direction):
    c = get_object_or_404(Collection.objects,
                          author__nickname=username, slug=slug)
    if request.method != 'POST':
        return redirect(c.get_url_path())

    vote = {'up': 1, 'down': -1}[direction]
    cv, new = CollectionVote.objects.get_or_create(
        collection=c, user=request.amo_user, defaults={'vote': vote})

    if not new:
        if cv.vote == vote:  # Double vote => cancel.
            cv.delete()
        else:
            cv.vote = vote
            cv.save()

    if request.is_ajax():
        return http.HttpResponse()
    else:
        return redirect(c.get_url_path())


def initial_data_from_request(request):
    return dict(author=request.amo_user, application_id=request.APP.id)


@login_required
def add(request):
    "Displays/processes a form to create a collection."
    data = {}
    if request.method == 'POST':
        form = forms.CollectionForm(
                request.POST, request.FILES,
                initial=initial_data_from_request(request))
        aform = forms.AddonsForm(request.POST)
        if form.is_valid():
            collection = form.save()

            if aform.is_valid():
                aform.save(collection)
            return http.HttpResponseRedirect(collection.get_url_path())
        else:
            data['addons'] = aform.clean_addon()
            data['comments'] = aform.clean_addon_comment()
    else:
        form = forms.CollectionForm()

    data['form'] = form
    return jingo.render(request, 'bandwagon/add.html', data)


def ajax_new(request):
    form = forms.CollectionForm(request.POST or None,
        initial={'author': request.amo_user,
                 'application_id': request.APP.id},
    )

    if request.method == 'POST':

        if form.is_valid():
            collection = form.save()
            CollectionUser(collection=collection, user=request.amo_user).save()
            addon_id = request.REQUEST['addon_id']
            a = Addon.objects.get(pk=addon_id)
            collection.add_addon(a)

            return http.HttpResponseRedirect(reverse('collections.ajax_list')
                                             + '?addon_id=%s' % addon_id)

    return jingo.render(request, 'bandwagon/ajax_new.html', {'form': form})


@login_required
def ajax_list(request):
    # Get collections associated with this user
    collections = request.amo_user.collections.manual()
    addon_id = int(request.GET['addon_id'])

    for collection in collections:
        # See if the collections contains the addon
        if addon_id in collection.addons.values_list('id', flat=True):
            collection.has_addon = True

    return jingo.render(request, 'bandwagon/ajax_list.html',
                {'collections': collections})


def _ajax_add_remove(request, op):
    id = request.POST['id']
    addon_id = request.POST['addon_id']

    c = Collection.objects.get(pk=id)

    if not c.owned_by(request.amo_user):
        return http.HttpResponseForbidden()

    a = Addon.objects.get(pk=addon_id)

    if op == 'add':
        c.add_addon(a)
    else:
        c.remove_addon(a)

    # redirect
    return http.HttpResponseRedirect(reverse('collections.ajax_list') +
                                             '?addon_id=%s' % addon_id)


def ajax_add(request):
    return _ajax_add_remove(request, 'add')


def ajax_remove(request):
    return _ajax_add_remove(request, 'remove')


@login_required
@owner_required
def edit(request, collection, username, slug):
    if request.method == 'POST':
        form = forms.CollectionForm(request.POST, request.FILES,
                                    initial=initial_data_from_request(request),
                                    instance=collection)
        if form.is_valid():
            collection = form.save()

            return http.HttpResponseRedirect(collection.get_url_path())
    else:
        form = forms.CollectionForm(instance=collection)

    data = dict(collection=collection,
                form=form,
                username=username,
                slug=slug)
    return jingo.render(request, 'bandwagon/edit.html', data)


@login_required
@owner_required(require_owner=False)
def edit_addons(request, collection, username, slug):
    if request.method == 'POST':
        form = forms.AddonsForm(request.POST)
        if form.is_valid():
            form.save(collection)
            return http.HttpResponseRedirect(collection.get_url_path())

    data = dict(collection=collection, username=username, slug=slug)
    return jingo.render(request, 'bandwagon/edit_addons.html', data)


@login_required
@owner_required
def edit_contributors(request, collection, username, slug):
    is_admin = acl.action_allowed(request, 'Admin', '%')

    data = dict(collection=collection, username=username, slug=slug,
                is_admin=is_admin)

    if is_admin:
        initial = dict(type=collection.type,
                       application=collection.application_id)
        data['admin_form'] = forms.AdminForm(initial=initial)

    if request.method == 'POST':
        if is_admin:
            admin_form = forms.AdminForm(request.POST)
            if admin_form.is_valid():
                admin_form.save(collection)

        form = forms.ContributorsForm(request.POST)
        if form.is_valid():
            form.save(collection)
            messages.success(request, _('Your collection has been updated.'))
            if form.cleaned_data['new_owner']:
                return http.HttpResponseRedirect(collection.get_url_path())
            return http.HttpResponseRedirect(
                    reverse('collections.edit_contributors',
                            args=[username, slug]))

    return jingo.render(request, 'bandwagon/edit_contributors.html', data)


@login_required
def delete(request, username, slug):
    collection = get_object_or_404(Collection, author__nickname=username,
                                   slug=slug)

    is_admin = acl.action_allowed(request, 'Admin', '%')

    if not (collection.is_owner(request.amo_user) or is_admin):
        return http.HttpResponseForbidden(
                _('This is not the collection you are looking for.'))

    data = dict(collection=collection, username=username, slug=slug,
                is_admin=is_admin)

    if request.method == 'POST':
        if request.POST['sure'] == '1':
            collection.delete()
            url = reverse('collections.user', args=[username])
            return http.HttpResponseRedirect(url)
        else:
            return http.HttpResponseRedirect(collection.get_url_path())

    return jingo.render(request, 'bandwagon/delete.html', data)
