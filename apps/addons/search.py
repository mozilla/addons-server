import logging
from operator import attrgetter

from django.conf import settings

import elasticutils
import pyes.exceptions as pyes

import amo
from .models import Addon
from bandwagon.models import Collection
from compat.models import AppCompat


log = logging.getLogger('z.es')


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'created', 'last_updated', 'weekly_downloads',
             'bayesian_rating', 'average_daily_users', 'status', 'type',
             'is_disabled')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name_sort'] = unicode(addon.name).lower()
    translations = addon.translations
    d['name'] = list(set(string for _, string in translations[addon.name_id]))
    d['description'] = list(set(string for _, string
                                in translations[addon.description_id]))
    d['summary'] = list(set(string for _, string
                            in translations[addon.summary_id]))
    d['app'] = [a.id for a in addon.compatible_apps]
    # This is an extra query, not good for perf.
    d['category'] = getattr(addon, 'category_ids', [])
    d['tags'] = getattr(addon, 'tag_list', [])
    if addon.current_version:
        d['platforms'] = [p.id for p in addon.current_version.supported_platforms]
    d['appversion'] = dict((app.id, {'min': appver.min.version_int,
                                     'max': appver.max.version_int})
                           for app, appver in addon.compatible_apps.items()
                           if appver)
    return d


def setup_mapping():
    """Set up the addons index mapping."""
    # Mapping describes how elasticsearch handles a document during indexing.
    # Most fields are detected and mapped automatically.
    appver = {'dynamic': False, 'properties': {'max': {'type': 'long'},
                                               'min': {'type': 'long'}}}
    m = {
        # Turn off analysis on name so we can sort by it.
        'name_sort': {'type': 'string', 'index': 'not_analyzed'},
        # Adding word-delimiter to split on camelcase and punctuation.
        'name': {'type': 'string', 'analyzer': 'standardPlusWordDelimiter'},
        'tags': {'type': 'string',
                 'index': 'not_analyzed',
                 'index_name': 'tag'},
        'platforms': {'type': 'integer', 'index_name': 'platform'},
        'appversion': {'properties': dict((app.id, appver)
                                          for app in amo.APP_USAGE)}
    }
    es = elasticutils.get_es()
    try:
        es.create_index_if_missing(settings.ES_INDEX)
    except pyes.ElasticSearchException:
        pass
    # Adjust the mapping for all models at once because fields are shared
    # across all doc types in an index. If we forget to adjust one of them
    # we'll get burned later on.
    for model in Addon, AppCompat, Collection:
        try:
            es.put_mapping(model._meta.app_label, {'properties': m},
                           settings.ES_INDEX)
        except pyes.ElasticSearchException, e:
            log.error(e)
