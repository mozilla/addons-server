import json
import re

from django import http
from django.conf import settings
from django.db.models import Count
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt

import jingo
import redisutils
from tower import ugettext_lazy as _lazy

import amo.utils
from amo.decorators import post_required
from addons.models import Addon
from .models import CompatReport

KEYS = (
    ('latest', _lazy('Latest')),
    ('beta', _lazy('Beta')),
    ('alpha', _lazy('Alpha')),
    ('other', _lazy('Other')),
)


def index(request, version=None):
    COMPAT = [v for v in settings.COMPAT if v['app'] == request.APP.id]
    if version is None and COMPAT:
        version = COMPAT[0]['version']

    redis = redisutils.connections['master']
    compat = redis.hgetall('compat:%s:%s' % (request.APP.id, version))
    versions = dict((k, int(v)) for k, v in compat.items())

    if version not in [v['version'] for v in COMPAT] or not versions:
        raise http.Http404()

    total = sum(versions.values())
    keys = [(k, unicode(v)) for k, v in KEYS]
    return jingo.render(request, 'compat/index.html',
                        {'versions': versions, 'total': total,
                         'version': version, 'keys': keys})


def details(request, version):
    return http.HttpResponse('go away')


@csrf_exempt
@post_required
def incoming(request):
    # Turn camelCase into snake_case.
    snake_case = lambda s: re.sub('[A-Z]+', '_\g<0>', s).lower()
    try:
        data = [(snake_case(k), v)
                for k, v in json.loads(request.raw_post_data).items()]
    except Exception:
        return http.HttpResponseBadRequest()

    # Build up a new report.
    report = CompatReport(client_ip=request.META.get('REMOTE_ADDR', ''))
    fields = CompatReport._meta.get_all_field_names()
    for key, value in data:
        if key in fields:
            setattr(report, key, value)
        else:
            return http.HttpResponseBadRequest()

    report.save()
    return http.HttpResponse(status=204)


def reporter(request):
    query = request.GET.get('guid')
    if query:
        qs = None
        if query.isdigit():
            qs = Addon.objects.filter(id=query)
        if not qs:
            qs = Addon.objects.filter(slug=query)
        if not qs:
            qs = Addon.objects.filter(guid=query)
        if not qs and len(query) > 4:
            qs = CompatReport.objects.filter(guid__startswith=query)
        if qs:
            return redirect('compat.reporter_detail', qs[0].guid)
    addons = (request.amo_user.addons.all()
              if request.user.is_authenticated() else [])
    return jingo.render(request, 'compat/reporter.html',
                        dict(query=query, addons=addons))


def reporter_detail(request, guid):
    qs = CompatReport.objects.filter(guid=guid)
    if not qs.exists():
        raise http.Http404()

    works_ = dict(qs.values_list('works_properly').annotate(Count('id')))
    works = {'success': works_.get(True, 0), 'failure': works_.get(False, 0)}

    if 'works_properly' in request.GET:
        qs = qs.filter(works_properly=request.GET['works_properly'])
    reports = amo.utils.paginate(request, qs.order_by('-created'), 100)

    addon = Addon.objects.filter(guid=guid)
    name = addon[0].name if addon else guid

    return jingo.render(request, 'compat/reporter_detail.html',
                        dict(reports=reports, works=works,
                             name=name, guid=guid))

