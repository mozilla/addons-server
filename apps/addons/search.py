from operator import attrgetter

from django.conf import settings

import elasticutils
import pyes.exceptions as pyes

from .models import Addon
from compat.models import AppCompat


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'name', 'created', 'last_updated', 'weekly_downloads',
             'bayesian_rating', 'average_daily_users', 'status', 'type',
             'is_disabled')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name'] = unicode(d['name']).lower()
    d['app'] = [a.id for a in addon.compatible_apps]
    # This is an extra query, not good for perf.
    d['category'] = getattr(addon, 'category_ids', [])
    return d


def setup_mapping():
    """Set up the addons index mapping."""
    # Mapping describes how elasticsearch handles a document during indexing.
    # Most fields are detected and mapped automatically.
    m = {
        # Turn off analysis on name so we can sort by it.
        'name': {
            'type': 'multi_field',
            'fields': {
                'name': {'type': 'string', 'index': 'not_analyzed'},
                'fulltext': {'type': 'string', 'index': 'analyzed'},
            },
        },
    }
    es = elasticutils.get_es()
    try:
        es.create_index_if_missing(settings.ES_INDEX)
    except pyes.ElasticSearchException:
        pass
    try:
        es.put_mapping(Addon._meta.app_label, {'properties': m},
                       settings.ES_INDEX)
    except pyes.ElasticSearchException:
        pass
    try:
        es.put_mapping(AppCompat._meta.app_label, {'properties': m},
                       settings.ES_INDEX)
    except pyes.ElasticSearchException:
        pass
