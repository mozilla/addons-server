import logging
from operator import attrgetter

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

import amo
import amo.search
from amo.models import SearchMixin
from addons.cron import reindex_addons
from addons.models import Persona
from bandwagon.cron import reindex_collections
from bandwagon.models import Collection
from compat.cron import compatibility_report
from compat.models import AppCompat
from lib.es.utils import create_index
from users.cron import reindex_users
from users.models import UserProfile
from versions.compare import version_int

from .models import Addon


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
        try:
            # This would otherwise get attached when by the transformer.
            d['weekly_downloads'] = addon.persona.popularity
            # Boost on popularity.
            d['boost'] = addon.persona.popularity ** .2
            d['has_theme_rereview'] = (
                addon.persona.rereviewqueuetheme_set.exists())
        except Persona.DoesNotExist:
            # The addon won't have a persona while it's being created.
            pass
    else:
        # Boost by the number of users on a logarithmic scale. The maximum
        # boost (11,000,000 users for adblock) is about 5x.
        d['boost'] = addon.average_daily_users ** .2
    # Double the boost if the add-on is public.
    if addon.status == amo.STATUS_PUBLIC and 'boost' in d:
        d['boost'] = max(d['boost'], 1) * 4

    # Indices for each language. languages is a list of locales we want to
    # index with analyzer if the string's locale matches.
    for analyzer, languages in amo.SEARCH_ANALYZER_MAP.iteritems():
        if (not settings.ES_USE_PLUGINS and
            analyzer in amo.SEARCH_ANALYZER_PLUGINS):
            continue

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


def get_alias():
    return settings.ES_INDEXES.get(SearchMixin.ES_ALIAS_KEY)


def create_new_index(index=None, config=None):
    if config is None:
        config = {}
    if index is None:
        index = get_alias()
    config['settings'] = {'index': INDEX_SETTINGS}
    config['mappings'] = get_mappings()
    create_index(index, config)


def get_mappings():
    # Mapping describes how elasticsearch handles a document during indexing.
    # Most fields are detected and mapped automatically.
    appver = {
        'dynamic': False,
        'properties': {
            'max': {'type': 'long'},
            'min': {'type': 'long'}
        }
    }
    mapping = {
        'properties': {
            'boost': {'type': 'float', 'null_value': 1.0},
            # Turn off analysis on name so we can sort by it.
            'name_sort': {'type': 'string', 'index': 'not_analyzed'},
            # Adding word-delimiter to split on camelcase and punctuation.
            'name': {'type': 'string', 'analyzer': 'standardPlusWordDelimiter'},
            'summary': {'type': 'string', 'analyzer': 'snowball'},
            'description': {'type': 'string', 'analyzer': 'snowball'},
            'tags': {'type': 'string', 'index': 'not_analyzed', 'index_name': 'tag'},
            'platforms': {'type': 'integer', 'index_name': 'platform'},
            'appversion': {'properties': dict((app.id, appver)
                                              for app in amo.APP_USAGE)},
        },
    }
    # Add room for language-specific indexes.
    for analyzer in amo.SEARCH_ANALYZER_MAP:
        if (not settings.ES_USE_PLUGINS
           and analyzer in amo.SEARCH_ANALYZER_PLUGINS):
            log.info('While creating mapping, skipping the %s analyzer' % analyzer)
            continue

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

    models = (Addon, AppCompat, Collection, UserProfile)
    return dict((m._meta.db_table, mapping) for m in models)


def reindex(index):
    indexers = [
        reindex_addons, reindex_collections, reindex_users, compatibility_report
    ]
    for indexer in indexers:
        log.info('Indexing %r' % indexer.__name__)
        try:
            indexer(index)
        except Exception:
            # We want to log this event but continue
            log.error('Indexer %r failed' % indexer.__name__)


INDEX_SETTINGS = {
    "analysis": {
        "analyzer": {
            "standardPlusWordDelimiter": {
                "tokenizer": "standard",
                "filter": ["standard", "wordDelim", "lowercase", "stop", "dict"]
            }
        },
        "filter": {
            "wordDelim": {
                "type": "word_delimiter",
                "preserve_original": True
            },
            "dict": {
                "type": "dictionary_decompounder",
                "word_list": [
                    "cool", "iris", "fire", "bug", "flag", "fox", "grease",
                    "monkey", "flash", "block", "forecast", "screen", "grab",
                    "cookie", "auto", "fill", "text", "all", "so", "think",
                    "mega", "upload", "download", "video", "map", "spring",
                    "fix", "input", "clip", "fly", "lang", "up", "down",
                    "persona", "css", "html", "http", "ball", "firefox",
                    "bookmark", "chat", "zilla", "edit", "menu", "menus",
                    "status", "bar", "with", "easy", "sync", "search", "google",
                    "time", "window", "js", "super", "scroll", "title", "close",
                    "undo", "user", "inspect", "inspector", "browser",
                    "context", "dictionary", "mail", "button", "url",
                    "password", "secure", "image", "new", "tab", "delete",
                    "click", "name", "smart", "down", "manager", "open",
                    "query", "net", "link", "blog", "this", "color", "select",
                    "key", "keys", "foxy", "translate", "word", ]
            }
        }
    }
}
