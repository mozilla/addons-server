from operator import attrgetter

from django.conf import settings

import elasticutils
import pyes.exceptions as pyes

from .models import Addon
from bandwagon.models import Collection
from compat.models import AppCompat


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'created', 'last_updated', 'weekly_downloads',
             'bayesian_rating', 'average_daily_users', 'status', 'type',
             'is_disabled')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name_sort'] = unicode(addon.name).lower()
    d['name'] = [string.lower()
                 for locale, string in addon.translations.get(addon.name_id, [])]
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
        'name_sort': {'type': 'string', 'index': 'not_analyzed'},
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
        except pyes.ElasticSearchException:
            pass
