import json
import re

from django import http
from django.db.models import Count
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

import jingo
from tower import ugettext as _

import amo
import amo.utils
from amo.decorators import post_required
from amo.utils import urlparams
from amo.urlresolvers import reverse
from addons.models import Addon
from search.utils import floor_version
from versions.compare import version_dict as vdict, version_int as vint
from .models import CompatReport, AppCompat, CompatTotals
from .forms import AppVerForm, CompatForm


def index(request, version=None):
    template = 'compat/index.html'
    COMPAT = [v for v in amo.COMPAT if v['app'] == request.APP.id]
    compat_dict = dict((v['main'], v) for v in COMPAT)
    if not COMPAT:
        return jingo.render(request, template, {'results': False})
    if version not in compat_dict:
        return http.HttpResponseRedirect(reverse('compat.index',
                                                 args=[COMPAT[0]['main']]))
    qs = AppCompat.search()
    binary = None

    initial = {'appver': '%s-%s' % (request.APP.id, version), 'type': 'all'}
    initial.update(request.GET.items())
    form = CompatForm(initial)
    if request.GET and form.is_valid():
        if form.cleaned_data['appver']:
            app, ver = form.cleaned_data['appver'].split('-')
            if int(app) != request.APP.id or ver != version:
                new = reverse('compat.index', args=[ver], add_prefix=False)
                url = '/%s%s' % (amo.APP_IDS[int(app)].short, new)
                type_ = form.cleaned_data['type'] or None
                return http.HttpResponseRedirect(urlparams(url, type=type_))

        if form.cleaned_data['type'] != 'all':
            binary = form.cleaned_data['type'] == 'binary'

    compat, app = compat_dict[version], str(request.APP.id)
    compat_queries = (
        ('prev', qs.query(**{
            'top_95.%s.%s' % (app, vint(compat['previous'])): True,
            'support.%s.max__gte' % app: vint(compat['previous'])})),
        ('top_95', qs.query(**{'top_95_all.%s' % app: True})),
        ('all', qs),
    )
    compat_levels = [(key, version_compat(qs, compat, app, binary))
                     for key, qs in compat_queries]
    usage_addons, usage_total = usage_stats(request, compat, app, binary)
    return jingo.render(request, template,
                        {'version': version,
                         'usage_addons': usage_addons,
                         'usage_total': usage_total,
                         'compat_levels': compat_levels,
                         'form': form,
                         'results': True,
                         'show_previous': request.GET.get('previous')})


def version_compat(qs, compat, app, binary):
    facets = []
    for v, prev in zip(compat['versions'], (None,) + compat['versions']):
        d = {'from': vint(v)}
        if prev:
            d['to'] = vint(prev)
        facets.append(d)
    # Pick up everything else for an Other count.
    facets.append({'to': vint(compat['versions'][-1])})
    facet = {'range': {'support.%s.max' % app: facets}}
    if binary is not None:
        qs = qs.query(binary=binary)
    qs = qs.facet(by_status=facet)
    result = qs[:0].raw()
    total_addons = result['hits']['total']
    ranges = result['facets']['by_status']['ranges']
    titles = compat['versions'] + (_('Other'),)
    faceted = [(v, r['count']) for v, r in zip(titles, ranges)]
    return total_addons, faceted


def usage_stats(request, compat, app, binary=None):
    # Get the list of add-ons for usage stats.
    qs = AppCompat.search().order_by('-usage.%s' % app).values_dict()
    if request.GET.get('previous'):
        qs = qs.filter(**{
            'support.%s.max__gte' % app: vint(compat['previous'])})
    else:
        qs = qs.filter(**{'support.%s.max__gte' % app: 0})
    if binary is not None:
        qs = qs.filter(binary=binary)
    addons = amo.utils.paginate(request, qs)
    for obj in addons.object_list:
        obj['usage'] = obj['usage'][app]
        obj['max_version'] = obj['max_version'][app]
    return addons, CompatTotals.objects.get(app=app).total


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

    form = AppVerForm(request.GET)
    if request.GET and form.is_valid() and form.cleaned_data['appver']:
        # Apply filters only if we have a good app/version combination.
        app, ver = form.cleaned_data['appver'].split('-')
        app = amo.APP_IDS[int(app)]
        ver = vdict(floor_version(ver))['major']  # 3.6 => 3

        # Ideally we'd have a `version_int` column to do strict version
        # comparing, but that's overkill for basic version filtering here.
        qs = qs.filter(app_guid=app.guid,
                       app_version__startswith=str(ver) + '.')

    works_ = dict(qs.values_list('works_properly').annotate(Count('id')))
    works = {'success': works_.get(True, 0), 'failure': works_.get(False, 0)}

    works_properly = request.GET.get('works_properly')
    if works_properly:
        qs = qs.filter(works_properly=works_properly)
    reports = amo.utils.paginate(request, qs.order_by('-created'), 100)

    addon = Addon.objects.filter(guid=guid)
    name = addon[0].name if addon else guid

    return jingo.render(request, 'compat/reporter_detail.html',
                        dict(reports=reports, works=works,
                             works_properly=works_properly,
                             name=name, guid=guid, form=form))
