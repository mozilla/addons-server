import logging
from operator import attrgetter

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count

import elasticutils.contrib.django as elasticutils
import pyes.exceptions as pyes

import amo
from amo.utils import create_es_index_if_missing
from .models import Addon
from bandwagon.models import Collection
from compat.models import AppCompat
from stats.models import ClientData
from users.models import UserProfile
from versions.compare import version_int

import mkt
from mkt.webapps.models import Installed


log = logging.getLogger('z.es')


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'slug', 'app_slug', 'created', 'last_updated',
             'weekly_downloads', 'bayesian_rating', 'average_daily_users',
             'status', 'type', 'hotness', 'is_disabled', 'premium_type',
             'uses_flash')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name_sort'] = unicode(addon.name).lower()
    translations = addon.translations
    d['name'] = list(set(string for _, string in translations[addon.name_id]))
    d['description'] = list(set(string for _, string
                                in translations[addon.description_id]))
    d['summary'] = list(set(string for _, string
                            in translations[addon.summary_id]))
    d['authors'] = [a.name for a in addon.listed_authors]
    d['device'] = getattr(addon, 'device_ids', [])
    # This is an extra query, not good for perf.
    d['category'] = getattr(addon, 'category_ids', [])
    d['tags'] = getattr(addon, 'tag_list', [])
    d['price'] = getattr(addon, 'price', 0.0)
    if addon.current_version:
        d['platforms'] = [p.id for p in
                          addon.current_version.supported_platforms]
    d['appversion'] = {}
    for app, appver in addon.compatible_apps.items():
        if appver:
            min_, max_ = appver.min.version_int, appver.max.version_int
        else:
            # Fake wide compatibility for search tools and personas.
            min_, max_ = 0, version_int('9999')
        d['appversion'][app.id] = dict(min=min_, max=max_)
    try:
        d['has_version'] = addon._current_version is not None
    except ObjectDoesNotExist:
        d['has_version'] = None
    d['app'] = [app.id for app in addon.compatible_apps.keys()]
    if addon.type == amo.ADDON_PERSONA:
        # This would otherwise get attached when by the transformer.
        d['weekly_downloads'] = addon.persona.popularity
        # Boost on popularity.
        d['_boost'] = addon.persona.popularity ** .2
    elif addon.type == amo.ADDON_WEBAPP:
        installed_ids = list(Installed.objects.filter(addon=addon)
                             .values_list('id', flat=True))
        d['popularity'] = d['_boost'] = len(installed_ids)

        # Calculate regional popularity for "mature regions"
        # (installs + reviews/installs from that region).
        installs = dict(ClientData.objects.filter(installed__in=installed_ids)
                        .annotate(region_counts=Count('region'))
                        .values_list('region', 'region_counts').distinct())
        for region in mkt.regions.ALL_REGION_IDS:
            cnt = installs.get(region, 0)
            if cnt:
                # Magic number (like all other scores up in this piece).
                d['popularity_%s' % region] = d['popularity'] + cnt * 10
            else:
                d['popularity_%s' % region] = len(installed_ids)
            d['_boost'] += cnt * 10
        d['app_type'] = (amo.ADDON_WEBAPP_PACKAGED if addon.is_packaged else
                         amo.ADDON_WEBAPP_HOSTED)

    else:
        # Boost by the number of users on a logarithmic scale. The maximum
        # boost (11,000,000 users for adblock) is about 5x.
        d['_boost'] = addon.average_daily_users ** .2
    # Double the boost if the add-on is public.
    if addon.status == amo.STATUS_PUBLIC:
        d['_boost'] = max(d['_boost'], 1) * 4

    # Indices for each language. languages is a list of locales we want to
    # index with analyzer if the string's locale matches.
    for analyzer, languages in amo.SEARCH_ANALYZER_MAP.iteritems():
        d['name_' + analyzer] = list(
            set(string for locale, string in translations[addon.name_id]
                if locale.lower() in languages))
        d['summary_' + analyzer] = list(
            set(string for locale, string in translations[addon.summary_id]
                if locale.lower() in languages))
        d['description_' + analyzer] = list(
            set(string for locale, string in translations[addon.description_id]
                if locale.lower() in languages))

    return d


def setup_mapping(index=None, aliased=True):
    """Set up the addons index mapping."""
    # Mapping describes how elasticsearch handles a document during indexing.
    # Most fields are detected and mapped automatically.
    appver = {'dynamic': False, 'properties': {'max': {'type': 'long'},
                                               'min': {'type': 'long'}}}
    mapping = {
        # Optional boosting during indexing.
        '_boost': {'name': '_boost', 'null_value': 1.0},
        'properties': {
            # Turn off analysis on name so we can sort by it.
            'name_sort': {'type': 'string', 'index': 'not_analyzed'},
            # Adding word-delimiter to split on camelcase and punctuation.
            'name': {'type': 'string',
                     'analyzer': 'standardPlusWordDelimiter'},
            'summary': {'type': 'string',
                        'analyzer': 'snowball'},
            'description': {'type': 'string',
                            'analyzer': 'snowball'},
            'tags': {'type': 'string',
                     'index': 'not_analyzed',
                     'index_name': 'tag'},
            'platforms': {'type': 'integer', 'index_name': 'platform'},
            'appversion': {'properties': dict((app.id, appver)
                                              for app in amo.APP_USAGE)},
        },
    }
    # Add room for language-specific indexes.
    for analyzer in amo.SEARCH_ANALYZER_MAP:
        mapping['properties']['name_' + analyzer] = {
            'type': 'string',
            'analyzer': analyzer,
        }
        mapping['properties']['summary_' + analyzer] = {
            'type': 'string',
            'analyzer': analyzer,
        }
        mapping['properties']['description_' + analyzer] = {
            'type': 'string',
            'analyzer': analyzer,
        }

    es = elasticutils.get_es()
    # Adjust the mapping for all models at once because fields are shared
    # across all doc types in an index. If we forget to adjust one of them
    # we'll get burned later on.
    for model in Addon, AppCompat, Collection, UserProfile:
        index = index or model._get_index()
        index = create_es_index_if_missing(index, aliased=aliased)
        try:
            es.put_mapping(model._meta.db_table, mapping, index)
        except pyes.ElasticSearchException, e:
            log.error(e)
