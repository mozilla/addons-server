from django import http
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404, redirect
from django.views import debug
from django.views.decorators.cache import never_cache

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.decorators import addon_view_factory
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon
from olympia.amo import messages, search
from olympia.amo.decorators import (
    json_view, permission_required, post_required)
from olympia.amo.utils import HttpResponseXSendFile, render
from olympia.files.models import File, FileUpload
from olympia.stats.indexers import DownloadCountIndexer
from olympia.versions.models import Version

from .decorators import admin_required
from .forms import AddonStatusForm, FileFormSet


log = olympia.core.logger.getLogger('z.zadmin')


@admin_required
def show_settings(request):
    settings_dict = debug.get_safe_settings()
    return render(request, 'zadmin/settings.html',
                  {'settings_dict': settings_dict, 'title': 'Settings!'})


@admin_required
def env(request):
    env = {}
    for k in request.META.keys():
        env[k] = debug.cleanse_setting(k, request.META[k])
    return render(request, 'zadmin/settings.html',
                  {'settings_dict': env, 'title': 'Env!'})


@admin.site.admin_view
def fix_disabled_file(request):
    file_ = None
    if request.method == 'POST' and 'file' in request.POST:
        file_ = get_object_or_404(File, id=request.POST['file'])
        if 'confirm' in request.POST:
            file_.unhide_disabled_file()
            messages.success(request, 'We have done a great thing.')
            return redirect('zadmin.fix-disabled')
    return render(request, 'zadmin/fix-disabled.html',
                  {'file': file_, 'file_id': request.POST.get('file', '')})


@admin_required
def elastic(request):
    es = search.get_es()

    ctx = {
        'nodes': es.nodes.stats(),
        'health': es.cluster.health(),
        'state': es.cluster.state(),
        'mappings': (
            (settings.ES_INDEXES['default'],
                AddonIndexer.get_mapping()),
            (settings.ES_INDEXES['stats_download_counts'],
                DownloadCountIndexer.get_mapping()),
        ),
    }
    return render(request, 'zadmin/elastic.html', ctx)


@permission_required(amo.permissions.ANY_ADMIN)
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return render(request, 'zadmin/index.html', {'log': log})


@admin_required
def addon_search(request):
    ctx = {}
    if 'q' in request.GET:
        q = ctx['q'] = request.GET['q']
        if q.isdigit():
            qs = Addon.objects.filter(id=int(q))
        else:
            qs = Addon.search().query(name__text=q.lower())[:100]
        if len(qs) == 1:
            return redirect('admin:addons_addon_change', qs[0].id)
        ctx['addons'] = qs
    return render(request, 'zadmin/addon-search.html', ctx)


@never_cache
@json_view
def general_search(request, app_id, model_id):
    if not admin.site.has_permission(request):
        raise PermissionDenied

    try:
        model = apps.get_model(app_id, model_id)
    except LookupError:
        raise http.Http404

    limit = 10
    obj = admin.site._registry[model]
    ChangeList = obj.get_changelist(request)
    # This is a hideous api, but uses the builtin admin search_fields API.
    # Expecting this to get replaced by ES so soon, that I'm not going to lose
    # too much sleep about it.
    args = [request, obj.model, [], [], [], [], obj.search_fields, [],
            obj.list_max_show_all, limit, [], obj]
    try:
        # python3.2+ only
        from inspect import signature
        if 'sortable_by' in signature(ChangeList.__init__).parameters:
            args.append('None')  # sortable_by is a django2.1+ addition
    except ImportError:
        pass
    cl = ChangeList(*args)
    qs = cl.get_queryset(request)
    # Override search_fields_response on the ModelAdmin object
    # if you'd like to pass something else back to the front end.
    lookup = getattr(obj, 'search_fields_response', None)
    return [{'value': o.pk, 'label': getattr(o, lookup) if lookup else str(o)}
            for o in qs[:limit]]


@admin_required
@addon_view_factory(qs=Addon.objects.all)
def addon_manage(request, addon):
    form = AddonStatusForm(request.POST or None, instance=addon)
    pager = amo.utils.paginate(
        request, Version.unfiltered.filter(addon=addon), 30)
    # A list coercion so this doesn't result in a subquery with a LIMIT which
    # MySQL doesn't support (at this time).
    versions = list(pager.object_list)
    files = File.objects.filter(version__in=versions).select_related('version')
    formset = FileFormSet(request.POST or None, queryset=files)

    if form.is_valid() and formset.is_valid():
        if 'status' in form.changed_data:
            ActivityLog.create(amo.LOG.CHANGE_STATUS, addon,
                               form.cleaned_data['status'])
            log.info('Addon "%s" status changed to: %s' % (
                addon.slug, form.cleaned_data['status']))
            form.save()

        for form in formset:
            if 'status' in form.changed_data:
                log.info('Addon "%s" file (ID:%d) status changed to: %s' % (
                    addon.slug, form.instance.id, form.cleaned_data['status']))
                form.save()
        return redirect('zadmin.addon_manage', addon.slug)

    # Build a map from file.id to form in formset for precise form display
    form_map = dict((form.instance.id, form) for form in formset.forms)
    # A version to file map to avoid an extra query in the template
    file_map = {}
    for file in files:
        file_map.setdefault(file.version_id, []).append(file)

    return render(request, 'zadmin/addon_manage.html', {
        'addon': addon, 'pager': pager, 'versions': versions, 'form': form,
        'formset': formset, 'form_map': form_map, 'file_map': file_map})


@admin_required
def download_file_upload(request, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)

    return HttpResponseXSendFile(request, upload.path,
                                 content_type='application/octet-stream')


@admin.site.admin_view
@post_required
@json_view
def recalc_hash(request, file_id):

    file = get_object_or_404(File, pk=file_id)
    file.size = storage.size(file.file_path)
    file.hash = file.generate_hash()
    file.save()

    log.info('Recalculated hash for file ID %d' % file.id)
    messages.success(request,
                     'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}
