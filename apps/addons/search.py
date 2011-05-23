import logging
from operator import attrgetter

from django.db.models import Max

import elasticutils

import amo.utils
from .models import Addon

log = logging.getLogger('z.addons.search')


def extract(addon):
    """Extract indexable attributes from an add-on."""
    # TODO: category, application, type
    attrs = ('id', 'name', 'created', 'modified', 'weekly_downloads',
             'bayesian_rating', 'status', 'type')
    d = dict(zip(attrs, attrgetter(*attrs)(addon)))
    d['name'] = unicode(d['name'])
    return d
