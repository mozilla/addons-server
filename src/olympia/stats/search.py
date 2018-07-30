import collections

from django.conf import settings

from olympia import amo
from olympia.applications.models import AppVersion
from olympia.lib.es.utils import create_index
from olympia.stats.models import (
    DownloadCount, StatsSearchMixin, UpdateCount)


# Number of elements to index at once in ES. The size of a dict to send to ES
# should be less than 1000 bytes, and the max size of messages to send to ES
# can be retrieved with the following command (look for
# "max_content_length_in_bytes"):
#  curl http://HOST:PORT/_nodes/?pretty
CHUNK_SIZE = 5000


def es_dict(items):
    if not items:
        return {}
    if hasattr(items, 'items'):
        items = items.items()
    return [{'k': key, 'v': value} for key, value in items]


# We index all the key/value pairs as lists of {'k': key, 'v': value} dicts
# so that ES doesn't include every single key in the update_counts mapping.
"""
{'addon': addon id,
 'date': date,
 'count': total count,
 'id': some unique id,
 'versions': [{'k': addon version, 'v': count}]
 'os': [{'k': amo.PLATFORM.name, 'v': count}]
 'locales': [{'k': locale, 'v': count}  # (all locales lower case)
 'apps': {amo.APP.guid: [{'k': app version, 'v': count}}]
 'status': [{'k': status, 'v': count}
"""


def extract_update_count(update, all_apps=None):
    doc = {'addon': update.addon_id,
           'date': update.date,
           'count': update.count,
           'id': update.id,
           '_id': '{0}-{1}'.format(update.addon_id, update.date),
           'versions': es_dict(update.versions),
           'os': [],
           'locales': [],
           'apps': [],
           'status': []}

    # Only count platforms we know about.
    if update.oses:
        os = collections.defaultdict(int)
        for key, count in update.oses.items():
            platform = None

            if unicode(key).lower() in amo.PLATFORM_DICT:
                platform = amo.PLATFORM_DICT[unicode(key).lower()]
            elif key in amo.PLATFORMS:
                platform = amo.PLATFORMS[key]

            if platform is not None:
                os[platform.name] += count
                doc['os'] = es_dict((unicode(k), v) for k, v in os.items())

    # Case-normalize locales.
    if update.locales:
        locales = collections.defaultdict(int)
        for locale, count in update.locales.items():
            try:
                locales[locale.lower()] += int(count)
            except ValueError:
                pass
        doc['locales'] = es_dict(locales)

    # Only count app/version combos we know about.
    if update.applications:
        apps = collections.defaultdict(dict)
        for guid, version_counts in update.applications.items():
            if guid not in amo.APP_GUIDS:
                continue
            app = amo.APP_GUIDS[guid]
            for version, count in version_counts.items():
                try:
                    apps[app.guid][version] = int(count)
                except ValueError:
                    pass
        doc['apps'] = dict((app, es_dict(vals)) for app, vals in apps.items())

    if update.statuses:
        doc['status'] = es_dict((k, v) for k, v in update.statuses.items()
                                if k != 'null')
    return doc


def extract_download_count(dl):
    return {'addon': dl.addon_id,
            'date': dl.date,
            'count': dl.count,
            'sources': es_dict(dl.sources) if dl.sources else {},
            'id': dl.id,
            '_id': '{0}-{1}'.format(dl.addon_id, dl.date)}


def extract_theme_user_count(user_count):
    return {'addon': user_count.addon_id,
            'date': user_count.date,
            'count': user_count.count,
            'id': user_count.id,
            '_id': '{0}-{1}'.format(user_count.addon_id, user_count.date)}


def get_all_app_versions():
    vals = AppVersion.objects.values_list('application', 'version')
    rv = collections.defaultdict(list)
    for app, version in vals:
        rv[app].append(version)
    return dict(rv)


def get_alias():
    return settings.ES_INDEXES.get(StatsSearchMixin.ES_ALIAS_KEY)


def create_new_index(index_name=None):
    if index_name is None:
        index_name = get_alias()
    config = {
        'mappings': get_mappings(),
    }
    create_index(index_name, config)


def reindex(index_name):
    from olympia.stats.management.commands.index_stats import index_stats
    index_stats(index_name)


def get_mappings():
    mapping = {
        'properties': {
            'id': {'type': 'long'},
            'boost': {'type': 'float', 'null_value': 1.0},
            'count': {'type': 'long'},
            'data': {
                'dynamic': 'true',
                'properties': {
                    'v': {'type': 'long'},
                    'k': {'type': 'keyword'}
                }
            },
            'date': {
                'format': 'dateOptionalTime',
                'type': 'date'
            }
        }
    }

    models = (DownloadCount, UpdateCount)
    return {model._meta.db_table: mapping for model in models}
