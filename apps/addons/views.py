from django import http
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import trans_real as translation

import jingo
from tower import ugettext_lazy as _lazy

import amo
from amo.utils import sorted_groupby
from amo import urlresolvers
from amo.urlresolvers import reverse
from bandwagon.models import Collection, CollectionFeature, CollectionPromo
from stats.models import GlobalStat
from tags.models import Tag
from .models import Addon


def author_addon_clicked(f):
    """Decorator redirecting clicks on "Other add-ons by author"."""
    def decorated(request, *args, **kwargs):
        redirect_id = request.GET.get('addons-author-addons-select', None)
        if not redirect_id:
            return f(request, *args, **kwargs)
        try:
            target_id = int(redirect_id)
            return http.HttpResponsePermanentRedirect(reverse(
                'addons.detail', args=[target_id]))
        except ValueError:
            return http.HttpResponseBadRequest('Invalid add-on ID.')
    return decorated


@author_addon_clicked
def addon_detail(request, addon_id):
    """Add-ons details page dispatcher."""
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    # addon needs to have a version and be valid for this app.
    if addon.type in request.APP.types:
        if addon.type == amo.ADDON_PERSONA:
            return persona_detail(request, addon)
        else:
            if not addon.current_version:
                raise http.Http404

            return extension_detail(request, addon)
    else:
        # Redirect to an app that supports this type.
        try:
            new_app = [a for a in amo.APP_USAGE if addon.type
                       in a.types][0]
        except IndexError:
            raise http.Http404
        else:
            prefixer = urlresolvers.get_url_prefix()
            prefixer.app = new_app.short
            return http.HttpResponsePermanentRedirect(reverse(
                'addons.detail', args=[addon.id]))


def extension_detail(request, addon):
    """Extensions details page."""

    # if current version is incompatible with this app, redirect
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return http.HttpResponsePermanentRedirect(reverse(
            'addons.detail', args=[addon.id]))

    # source tracking
    src = request.GET.get('src', 'addondetail')

    # get satisfaction only supports en-US
    lang = translation.to_locale(translation.get_language())
    addon.has_satisfaction = (lang == 'en_US' and
                              addon.get_satisfaction_company)

    # other add-ons from the same author(s)
    author_addons = (Addon.objects.valid().only_translations()
                     .exclude(id=addon.id)
                     .filter(addonuser__listed=True,
                             authors__in=addon.listed_authors).distinct())

    # tags
    (dev_tags, user_tags) = addon.tags_partitioned_by_developer

    current_user_tags = []

    if request.user.is_authenticated():
        current_user_tags = user_tags.filter(
                addon_tags__user=request.amo_user)

    # addon recommendations
    recommended = Addon.objects.valid().only_translations().filter(
        recommended_for__addon=addon)[:5]

    # popular collections this addon is part of
    coll_show_count = 3
    collections = Collection.objects.listed().filter(
        addons=addon, application__id=request.APP.id)
    other_coll_count = max(0, collections.count() - coll_show_count)
    popular_coll = collections.order_by('-subscribers')[:coll_show_count]

    # this user's collections
    user_collections = _details_collections_dropdown(request, addon)

    data = {
        'addon': addon,
        'author_addons': author_addons,

        'src': src,

        'dev_tags': dev_tags,
        'user_tags': user_tags,
        'current_user_tags': current_user_tags,

        'recommendations': recommended,

        'collections': popular_coll,
        'other_collection_count': other_coll_count,
        'user_collections': user_collections,
    }
    return jingo.render(request, 'addons/details.html', data)


def _details_collections_dropdown(request, addon):
    """Returns the collections which should be shown on an add-on details
        page for a logged in user. This is used in the "Add to a collection..."
        dropdown.  Rules to be in this list:
            - user is logged in
            - collection is not synchronized
            - user is an admin or publisher of the collection
            - collection application matches current APP
            - current add-on is not already in the collection

    This takes care of all but #5, for that we had to resort to raw() :(
        profile.collections.filter(
            Q(type=amo.COLLECTION_NORMAL) | Q(type=amo.COLLECTION_FEATURED),
            Q(collectionuser__role=amo.COLLECTION_ROLE_ADMIN) |
            Q(collectionuser__role=amo.COLLECTION_ROLE_PUBLISHER),
            application__id=request.APP.id)
    """
    if request.user.is_authenticated():
        profile = request.amo_user
    else:
        return []

    sql = """
            SELECT DISTINCT
                collections.id
            FROM
                collections_users as cu
            INNER JOIN
                collections ON
                (cu.collection_id = collections.id)
            LEFT JOIN
                addons_collections AS ac ON
                (ac.collection_id = collections.id AND ac.addon_id IN (%s))
            WHERE
                cu.user_id = %s
            AND cu.role IN (%s,%s) AND ac.addon_id IS NULL
            AND collections.collection_type IN (%s,%s)
            AND collections.application_id = %s
    """
    params = [addon.id, profile.id, amo.COLLECTION_ROLE_PUBLISHER,
              amo.COLLECTION_ROLE_ADMIN, amo.COLLECTION_NORMAL,
              amo.COLLECTION_FEATURED, request.APP.id]
    collections = Collection.objects.raw(sql, params)

    ids = [i.id for i in collections]

    if ids:
        return Collection.objects.filter(id__in=ids)
    else:
        return []


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
        # Remora users persona.author despite there being a display_username
        'author_gallery': settings.PERSONAS_USER_ROOT % persona.author,
    }

    return jingo.render(request, 'addons/personas_detail.html', data)


class HomepageFilter(object):
    """
    key: the GET param we look at
    default: the default key we should use
    """

    opts = (('featured', _lazy('Featured')),
            ('popular', _lazy('Popular')),
            ('new', _lazy('Recently Added')),
            ('updated', _lazy('Recently Updated')))

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
        return self._filter(field) & self.base_queryset

    def _filter(self, field):
        qs = Addon.objects
        if field == 'popular':
            return (qs.order_by('-weekly_downloads')
                    .with_index(addons='downloads_type_idx'))
        elif field == 'new':
            return (qs.order_by('-created')
                    .with_index(addons='created_type_idx'))
        elif field == 'updated':
            return (qs.order_by('-last_updated')
                    .with_index(addons='last_updated_type_idx'))
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
        lang = translation.to_language(translation.get_language())
        locale = Q(locale='') | Q(locale=lang)
        promos = (CollectionPromo.objects.filter(locale)
                  .filter(collection_feature__in=features)
                  .transform(CollectionPromo.transformer))
        groups = sorted_groupby(promos, 'collection_feature_id')

        # We key by feature_id and locale, so we can favor locale specific
        # promos.
        promo_dict = {}
        for feature_id, v in groups:
            promo = v.next()
            key = (feature_id, translation.to_language(promo.locale))
            promo_dict[key] = promo

        rv = {}
        # If we can, we favor locale specific collections.
        for feature in features:
            key = (feature.id, lang)
            if key not in promo_dict:
                key = (feature.id, '')

            # We only want to see public add-ons on the front page.
            c = promo_dict[key].collection
            c.public_addons = c.addons.all() & Addon.objects.public()
            rv[feature] = c

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
