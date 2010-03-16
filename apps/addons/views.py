from django import http
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import translation

import jingo
from l10n import ugettext as _

import amo
from amo import urlresolvers
from amo.urlresolvers import reverse

from bandwagon.models import Collection, CollectionFeature, CollectionPromo
from users.models import UserProfile
from stats.models import GlobalStat
from .models import Addon


def author_addon_clicked(f):
    """Decorator redirecting clicks on "Other add-ons by author"."""
    def decorated(request, *args, **kwargs):
        try:
            target_id = int(request.GET.get('addons-author-addons-select'))
            return http.HttpResponsePermanentRedirect(reverse(
                'addons.detail', args=[target_id]))
        except TypeError:
            return f(request, *args, **kwargs)
    return decorated


@author_addon_clicked
def addon_detail(request, addon_id):
    """Add-ons details page."""
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)

    # if current version is incompatible with this app, redirect
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return http.HttpResponsePermanentRedirect(reverse(
            'addons.detail', args=[addon_id]))

    addon.is_searchengine = (addon.type == amo.ADDON_SEARCH)

    # source tracking
    src = request.GET.get('src', 'addondetail')

    # get satisfaction only supports en-US
    lang = translation.to_locale(translation.get_language())
    addon.has_satisfaction = (lang == 'en_US' and
                              addon.get_satisfaction_company)

    # other add-ons from the same author(s)
    author_addons = Addon.objects.valid().filter(
        addonuser__listed=True, authors__in=addon.listed_authors).distinct()

    # tags
    tags = addon.tags.not_blacklisted()
    dev_tags = tags.filter(addon_tags__user__in=addon.authors.all())
    user_tags = tags.exclude(addon_tags__user__in=addon.authors.all())

    # addon recommendations
    recommended = Addon.objects.valid().filter(
        recommended_for__addon=addon)[:5]

    # popular collections this addon is part of
    coll_show_count = 3
    collections = Collection.objects.listed().filter(
        addons=addon, application__id=request.APP.id)
    other_coll_count = collections.count() - coll_show_count
    popular_coll = collections.order_by('-subscribers')[:coll_show_count]

    # this user's collections
    if request.user.is_authenticated():
        profile = UserProfile.objects.get(user=request.user)
        user_collections = profile.collections.filter(
            collectionuser__role=amo.COLLECTION_ROLE_ADMIN)
    else:
        user_collections = []

    data = {
        'addon': addon,
        'author_addons': author_addons,

        'src': src,

        'dev_tags': dev_tags,
        'user_tags': user_tags,

        'recommendations': recommended,

        'collections': popular_coll,
        'other_collection_count': other_coll_count,
        'user_collections': user_collections,
    }
    return jingo.render(request, 'addons/details.html', data)


class HomepageFilter(object):
    """
    key: the GET param we look at
    default: the default key we should use
    """

    opts = (('featured', _('Featured')),
            ('popular', _('Popular')),
            ('new', _('Just Added')),
            ('updated', _('Updated')))

    def __init__(self, request, base, key, default):
        self.opts_dict = dict(self.opts)
        self.request = request
        self.base_queryset = base
        self.field, self.title = self.options(self.request, key, default)
        self.qs = self.filter(self.field)

    def options(self, request, key, default):
        """Get the (option, title) pair we should according to the request."""
        if key in request.GET and request.GET[key] in self.opts_dict:
            opt = request.GET[key]
        else:
            opt = default
        return opt, self.opts_dict[opt]

    def all(self):
        """Get a full mapping of {option: queryset}."""
        return dict((field, self.filter(field)) for field in dict(self.opts))

    def filter(self, field):
        """Get the queryset for the given field."""
        return self.base_queryset & self._filter(field).distinct()

    def _filter(self, field):
        qs = Addon.objects
        if field == 'popular':
            return qs.order_by('-bayesian_rating')
        elif field == 'new':
            return qs.order_by('-created')
        elif field == 'updated':
            return qs.order_by('-last_updated')
        else:
            # It's ok to cache this for a while...it'll expire eventually.
            return qs.featured(self.request.APP).order_by('?')


def home(request):
    # Add-ons.
    base = Addon.objects.listed(request.APP).exclude(type=amo.ADDON_PERSONA)
    filter = HomepageFilter(request, base, key='browse', default='featured')
    addon_sets = dict((key, qs[:4]) for key, qs in filter.all().items())

    # Collections.
    q = Collection.objects.filter(listed=True, application=request.APP.id)
    collections = q.order_by('-weekly_subscribers')[:3]
    promobox = CollectionPromoBox(request)

    # Global stats.
    try:
        gs = GlobalStat.objects
        downloads = gs.filter(name='addon_total_downloads').latest()
        pings = gs.filter(name='addon_total_updatepings').latest()
    except GlobalStat.DoesNotExist:
        downloads = pings = None

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings,
                         'filter': filter, 'addon_sets': addon_sets,
                         'collections': collections, 'promobox': promobox,
                        })


class CollectionPromoBox(object):

    def __init__(self, request):
        self.request = request

    def features(self):
        return CollectionFeature.objects.all()

    def collections(self):
        features = self.features()
        lang = translation.get_language()
        locale = Q(locale='') | Q(locale=lang)
        promos = (CollectionPromo.objects.filter(locale)
                  .filter(collection_feature__in=features)
                  .select_related('collection'))
        # Get a localized collection, if possible.
        rv = {}
        pdict = dict(((p.collection_feature_id, p.locale), p) for p in promos)
        for feature in features:
            _key = (feature.id, lang)
            key = _key if _key in pdict else (feature.id, '')
            rv[feature] = pdict[key].collection
        return rv

    def __nonzero__(self):
        return self.request.APP == amo.FIREFOX
