import collections

import elasticutils
import pyes.exceptions as pyes

import amo
from applications.models import AppVersion
from stats.models import CollectionCount, DownloadCount, UpdateCount


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

            if str(key).lower() in amo.PLATFORM_DICT:
                platform = amo.PLATFORM_DICT[str(key).lower()]
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
            'id': dl.id}


def extract_addon_collection(collection_count, addon_collections,
                             collection_stats):
    addon_collection_count = sum([c.count for c in addon_collections])
    collection_stats = dict([[c.name, c.count] for c in collection_stats])
    return {'date': collection_count.date,
            'id': collection_count.collection_id,
            'count': collection_count.count,
            'data': es_dict({
                'downloads': addon_collection_count,
                'votes_up': collection_stats.get('new_votes_up', 0),
                'votes_down': collection_stats.get('new_votes_down', 0),
                'subscribers': collection_stats.get('new_subscribers', 0),
            })}


def get_all_app_versions():
    vals = AppVersion.objects.values_list('application', 'version')
    rv = collections.defaultdict(list)
    for app, version in vals:
        rv[app].append(version)
    return dict(rv)


def setup_indexes():
    es = elasticutils.get_es()
    for model in CollectionCount, DownloadCount, UpdateCount:
        index = model._get_index()
        try:
            es.create_index_if_missing(index)
        except pyes.ElasticSearchException:
            pass

        mapping = {
            'properties': {
                'id': {'type': 'long'},
                'count': {'type': 'long'},
                'data': {'dynamic': 'true',
                         'properties': {
                            'v': {'type': 'long'},
                            'k': {'type': 'string'}
                        }
                },
                'date': {'format': 'dateOptionalTime',
                         'type': 'date'}
            }
        }
        es.put_mapping(model._meta.db_table, mapping,
                       model._get_index())
