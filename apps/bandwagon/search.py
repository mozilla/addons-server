from operator import attrgetter


def extract(collection):
    attrs = ('id', 'name', 'slug', 'author_username', 'type', 'application_id')
    d = dict(zip(attrs, attrgetter(*attrs)(collection)))
    d['app'] = d.pop('application_id')
    d['name'] = unicode(d['name'])
    d['name_sort'] = unicode(d['name']).lower()
    return d
