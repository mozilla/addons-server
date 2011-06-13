from operator import attrgetter

import pyes.exceptions as pyes


def extract(collection):
    attrs = ('id', 'name', 'slug', 'author_username', 'type', 'application_id')
    d = dict(zip(attrs, attrgetter(*attrs)(collection)))
    d['app'] = d.pop('application_id')
    d['name'] = unicode(d['name'])  # Coerce to unicode.
    return d
