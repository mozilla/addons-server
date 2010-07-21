from django import http
from django.shortcuts import get_object_or_404, redirect

import jingo
from tower import ugettext_lazy as _lazy

import amo.utils
from addons.models import Addon
from addons.views import BaseFilter
from translations.query import order_by_translation
from .models import Collection, CollectionAddon


def legacy_redirect(self, uuid):
    # Nicknames have a limit of 30, so len == 36 implies a uuid.
    key = 'uuid' if len(uuid) == 36 else 'nickname'
    c = get_object_or_404(Collection.objects, **{key: uuid})
    return redirect(c.get_url_path())


def collection_listing(request):
    return http.HttpResponse()


def user_listing(request, user):
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


def collection_detail(request, user, slug):
    # TODO: owner=user when dd adds owner to collections
    cn = get_object_or_404(Collection.objects, slug=slug)
    base = cn.addons.all() & Addon.objects.listed(request.APP)
    filter = CollectionAddonFilter(request, base,
                                   key='sort', default='popular')
    notes = get_notes(cn)
    count = base.with_index(addons='type_status_inactive_idx').count()
    addons = amo.utils.paginate(request, filter.qs, count=count)
    return jingo.render(request, 'bandwagon/collection_detail.html',
                        {'collection': cn, 'filter': filter,
                         'addons': addons, 'notes': notes})


def get_notes(collection):
    # This might hurt in a big collection with lots of notes.
    # It's a generator so we don't evaluate anything by default.
    notes = CollectionAddon.objects.filter(collection=collection,
                                           comments__isnull=False)
    rv = {}
    for note in notes:
        rv[note.addon_id] = note.comments
    yield rv
