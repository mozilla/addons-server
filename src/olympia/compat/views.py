import json
import re

from django import http
from django.db.models import Count
from django.db.transaction import non_atomic_requests
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

from olympia import amo
from olympia.addons.decorators import owner_or_unlisted_reviewer
from olympia.addons.models import Addon
from olympia.amo.decorators import post_required
from olympia.amo.utils import paginate, render
from olympia.search.utils import floor_version
from olympia.versions.compare import version_dict as vdict

from .forms import AppVerForm
from .models import CompatReport


@csrf_exempt
@post_required
@non_atomic_requests
def incoming(request):
    # Turn camelCase into snake_case.
    def snake_case(s):
        return re.sub('[A-Z]+', '_\g<0>', s).lower()

    try:
        data = [
            (snake_case(k), v) for k, v in json.loads(request.body).items()
        ]
    except Exception:
        return http.HttpResponseBadRequest()

    # Build up a new report.
    report = CompatReport(client_ip=request.META.get('REMOTE_ADDR', ''))
    fields = [field.name for field in CompatReport._meta.get_fields()]
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
            qs = Addon.objects.filter(id=query)
        if not qs:
            qs = Addon.objects.filter(slug=query)
        if not qs:
            qs = Addon.objects.filter(guid=query)
        if not qs and len(query) > 4:
            qs = CompatReport.objects.filter(guid__startswith=query)
        if qs:
            guid = qs[0].guid
            addon = Addon.objects.get(guid=guid)
            if addon.has_listed_versions() or owner_or_unlisted_reviewer(
                request, addon
            ):
                return redirect('compat.reporter_detail', guid)
    addons = (
        Addon.objects.filter(authors=request.user)
        if request.user.is_authenticated()
        else []
    )
    return render(
        request, 'compat/reporter.html', dict(query=query, addons=addons)
    )


@non_atomic_requests
def reporter_detail(request, guid):
    try:
        addon = Addon.objects.get(guid=guid)
    except Addon.DoesNotExist:
        addon = None
    name = addon.name if addon else guid
    qs = CompatReport.objects.filter(guid=guid)
    show_listed_only = addon and not owner_or_unlisted_reviewer(request, addon)

    if addon and not addon.has_listed_versions() and show_listed_only:
        # Not authorized? Let's pretend this addon simply doesn't exist.
        name = guid
        qs = CompatReport.objects.none()
    elif show_listed_only:
        unlisted_versions = addon.versions.filter(
            channel=amo.RELEASE_CHANNEL_UNLISTED
        ).values_list('version', flat=True)
        qs = qs.exclude(version__in=unlisted_versions)

    form = AppVerForm(request.GET)
    if request.GET and form.is_valid() and form.cleaned_data['appver']:
        # Apply filters only if we have a good app/version combination.
        version = form.cleaned_data['appver']
        ver = vdict(floor_version(version))['major']  # 3.6 => 3

        # Ideally we'd have a `version_int` column to do strict version
        # comparing, but that's overkill for basic version filtering here.
        qs = qs.filter(
            app_guid=amo.FIREFOX.guid, app_version__startswith=str(ver) + '.'
        )

    works_ = dict(qs.values_list('works_properly').annotate(Count('id')))
    works = {'success': works_.get(True, 0), 'failure': works_.get(False, 0)}

    works_properly = request.GET.get('works_properly')
    if works_properly:
        qs = qs.filter(works_properly=works_properly)
    reports = paginate(request, qs.order_by('-created'), 100)

    return render(
        request,
        'compat/reporter_detail.html',
        dict(
            reports=reports,
            works=works,
            works_properly=works_properly,
            name=name,
            guid=guid,
            form=form,
        ),
    )
