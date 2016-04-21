import json
import re

from django import http
from django.db.models import Count
from django.db.transaction import non_atomic_requests
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from olympia import amo
from olympia.amo import utils as amo_utils
from olympia.addons.decorators import owner_or_unlisted_reviewer
from olympia.amo.decorators import post_required
from olympia.addons.models import Addon
from olympia.search.utils import floor_version
from olympia.versions.compare import version_dict as vdict

from .models import CompatReport
from .forms import AppVerForm


@csrf_exempt
@post_required
@non_atomic_requests
def incoming(request):
    # Turn camelCase into snake_case.
    def snake_case(s):
        return re.sub('[A-Z]+', '_\g<0>', s).lower()

    try:
        data = [(snake_case(k), v)
                for k, v in json.loads(request.body).items()]
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


@non_atomic_requests
def reporter(request):
    query = request.GET.get('guid')
    if query:
        qs = None
        if query.isdigit():
            qs = Addon.with_unlisted.filter(id=query)
        if not qs:
            qs = Addon.with_unlisted.filter(slug=query)
        if not qs:
            qs = Addon.with_unlisted.filter(guid=query)
        if not qs and len(query) > 4:
            qs = CompatReport.objects.filter(guid__startswith=query)
        if qs:
            guid = qs[0].guid
            addon = Addon.with_unlisted.get(guid=guid)
            if addon.is_listed or owner_or_unlisted_reviewer(request, addon):
                return redirect('compat.reporter_detail', guid)
    addons = (Addon.with_unlisted.filter(authors=request.user)
              if request.user.is_authenticated() else [])
    return render(request, 'compat/reporter.html',
                  dict(query=query, addons=addons))


@non_atomic_requests
def reporter_detail(request, guid):
    try:
        addon = Addon.with_unlisted.get(guid=guid)
    except Addon.DoesNotExist:
        addon = None
    name = addon.name if addon else guid
    qs = CompatReport.objects.filter(guid=guid)

    if (addon and not addon.is_listed and
            not owner_or_unlisted_reviewer(request, addon)):
        # Not authorized? Let's pretend this addon simply doesn't exist.
        name = guid
        qs = CompatReport.objects.none()

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
    reports = amo_utils.paginate(request, qs.order_by('-created'), 100)

    return render(request, 'compat/reporter_detail.html',
                  dict(reports=reports, works=works,
                       works_properly=works_properly,
                       name=name, guid=guid, form=form))
