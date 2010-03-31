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
from tags.models import Tag
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
    """Add-ons details page dispatcher."""
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    if addon.type.id in request.APP.types:
        if addon.type.id == amo.ADDON_PERSONA:
            return persona_detail(request, addon)
        else:
            return extension_detail(request, addon)
    else:
        raise http.Http404


def extension_detail(request, addon):
    """Extensions details page."""

    # if current version is incompatible with this app, redirect
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return http.HttpResponsePermanentRedirect(reverse(
            'addons.detail', args=[addon.id]))

    addon.is_searchengine = (addon.type.id == amo.ADDON_SEARCH)

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


def persona_detail(request, addon):
    """Details page for Personas."""
    persona = addon.persona

    # this persona's categories
    categories = addon.categories.filter(application=request.APP.id)
    if categories:
        category_personas = Addon.objects.valid().filter(
            categories=categories[0]).exclude(pk=addon.pk).order_by('?')[:6]
    else:
        category_personas = None

    # tags
    tags = addon.tags.not_blacklisted()
    dev_tags = tags.filter(addon_tags__user__in=addon.authors.all())
    user_tags = tags.exclude(addon_tags__user__in=addon.authors.all())

    # other personas from the same author(s)
    other_personas_regular = Q(addonuser__listed=True,
                               authors__in=addon.listed_authors)
    other_personas_legacy = Q(persona__author=persona.author)
    author_personas = Addon.objects.valid().filter(
        other_personas_regular | other_personas_legacy,
        type=amo.ADDON_PERSONA).exclude(
            pk=addon.pk).distinct().select_related('persona')[:3]

    data = {
        'addon': addon,
        'persona': persona,
        'categories': categories,
        'author_personas': author_personas,
        'category_personas': category_personas,
        'dev_tags': dev_tags,
        'user_tags': user_tags,
    }

    return jingo.render(request, 'addons/personas_detail.html', data)


class HomepageFilter(object):
    """
    key: the GET param we look at
    default: the default key we should use
    """

    opts = (('featured', _('Featured')),
            ('popular', _('Popular')),
            ('new', _('Recently Added')),
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

    # Top tags.
    top_tags = Tag.objects.not_blacklisted().select_related(
        'tagstat').order_by('-tagstat__num_addons')[:10]

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings,
                         'filter': filter, 'addon_sets': addon_sets,
                         'collections': collections, 'promobox': promobox,
                         'top_tags': top_tags,
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


def eula(request, addon_id, file_id):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    return jingo.render(request, 'addons/eula.html', {'addon': addon})


def meet_the_developer(request, addon_id, extra=None):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    return jingo.render(request, 'addons/meet_the_developer.html',
                        {'addon': addon})


def discovery(request):
    return jingo.render(request, 'addons/discovery.html')
