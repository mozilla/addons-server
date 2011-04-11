from django import http
from django.conf import settings

import jingo
import redisutils
from tower import ugettext_lazy as _lazy

KEYS = (
    ('latest', _lazy('Latest')),
    ('beta', _lazy('Beta')),
    ('alpha', _lazy('Alpha')),
    ('other', _lazy('Other')),
)


def index(request, version=None):
    version = version or settings.COMPAT[0]['version']
    if version not in [v['version'] for v in settings.COMPAT]:
        raise http.Http404()
    redis = redisutils.connections['master']
    compat = redis.hgetall('compat:%s:%s' % (request.APP.id, version))
    versions = dict((k, int(v)) for k, v in compat.items())
    print versions
    total = sum(versions.values())
    keys = [(k, unicode(v)) for k, v in KEYS]
    return jingo.render(request, 'compat/index.html',
                        {'versions': versions, 'total': total,
                         'version': version, 'keys': keys})


def details(request, version):
    pass
