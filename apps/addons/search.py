import logging
from operator import attrgetter

from django.conf import settings

import elasticutils

from .models import Addon

log = logging.getLogger('z.addons.search')


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'name', 'created', 'last_updated', 'weekly_downloads',
             'bayesian_rating', 'average_daily_users', 'status', 'type')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name'] = unicode(d['name'])
    d['app'] = [a.id for a in addon.compatible_apps]
    # This is an extra query, not good for perf.
    d['category'] = list(addon.categories.values_list('id', flat=True))
    return d


def setup_mapping():
    """Set up the addons index mapping."""
    # Mapping describes how elasticsearch handles a document during indexing.
    # Most fields are detected and mapped automatically.
    m = {
        # Turn off analysis on name so we can sort by it.
        'name': {'index': 'not_analyzed', 'type': 'string'},
    }
    es = elasticutils.get_es()
    if settings.ES_INDEX not in es.get_indices():
        es.create_index(settings.ES_INDEX)
        es.put_mapping(Addon._meta.app_label, {'properties': m},
                       settings.ES_INDEX)
