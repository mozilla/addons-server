from operator import attrgetter

from django.conf import settings

import elasticutils
import pyes.exceptions as pyes

from .models import Addon, Feature


def extract(addon):
    """Extract indexable attributes from an add-on."""
    attrs = ('id', 'name', 'created', 'last_updated', 'weekly_downloads',
             'bayesian_rating', 'average_daily_users', 'status', 'type',
             'is_disabled', 'hotness')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    # Coerce the Translation into a string.
    d['name'] = unicode(d['name'])
    d['app'] = [a.id for a in addon.compatible_apps]
    # This is an extra query, not good for perf.
    d['category'] = list(addon.categories.values_list('id', flat=True))
    # Another extra query.
    features = (Feature.objects.filter(addon=addon)
                .values_list('locale', 'application'))
    d['featured'] = [app for locale, app in features if locale is None]
    # Guard `app not in featured` so we don't get dupes. Global featured takes
    # precedent over locale-featured.
    d['featured_locale'] = [{locale: app} for locale, app in features
                            if locale is not None and app not in d['featured']]
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
    try:
        es.create_index(settings.ES_INDEX)
        es.put_mapping(Addon._meta.app_label, {'properties': m},
                       settings.ES_INDEX)
    except pyes.ElasticSearchException:
        pass
