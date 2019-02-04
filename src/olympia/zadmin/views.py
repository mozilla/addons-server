import csv

from django import http
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404, redirect
from django.views import debug
from django.views.decorators.cache import never_cache

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog, AddonLog
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, AddonUser, CompatOverride
from olympia.amo import messages, search
from olympia.amo.decorators import (
    json_view, login_required, permission_required, post_required)
from olympia.amo.mail import DevEmailBackend
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, chunked, render
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.compat import FIREFOX_COMPAT
from olympia.compat.models import AppCompat, CompatTotals
from olympia.files.models import File, FileUpload
from olympia.search.indexers import get_mappings as get_addons_mappings
from olympia.stats.search import get_mappings as get_stats_mappings
from olympia.versions.compare import version_int as vint
from olympia.versions.models import Version
from olympia.zadmin.forms import SiteEventForm
from olympia.zadmin.models import SiteEvent

from . import tasks
from .decorators import admin_required
from .forms import (
    AddonStatusForm, CompatForm, DevMailerForm, FeaturedCollectionFormSet,
    FileFormSet, MonthlyPickFormSet, YesImSure)
from .models import EmailPreviewTopic


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


@login_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application']

    versions = AppVersion.objects.filter(application=app_id)
    return {'choices': [(v.id, v.version) for v in versions]}


@permission_required(amo.permissions.REVIEWS_ADMIN)
def email_preview_csv(request, topic):
    resp = http.HttpResponse()
    resp['Content-Type'] = 'text/csv; charset=utf-8'
    resp['Content-Disposition'] = "attachment; filename=%s.csv" % (topic)
    writer = csv.writer(resp)
    fields = ['from_email', 'recipient_list', 'subject', 'body']
    writer.writerow(fields)
    rs = EmailPreviewTopic(topic=topic).filter().values_list(*fields)
    for row in rs:
        writer.writerow([r.encode('utf8') for r in row])
    return resp


@admin_required
def compat(request):
    minimum = 10
    ratio = .8
    binary = None

    # Expected usage:
    #     For Firefox 8.0 reports:      ?appver=1-8.0
    #     For over 70% incompatibility: ?appver=1-8.0&ratio=0.7
    #     For binary-only add-ons:      ?appver=1-8.0&type=binary
    data = {'appver': '%s' % FIREFOX_COMPAT[0]['main'],
            'minimum': minimum, 'ratio': ratio, 'type': 'all'}
    version = data['appver']
    data.update(request.GET.items())

    form = CompatForm(data)
    if request.GET and form.is_valid():
        version = form.cleaned_data['appver']
        if form.cleaned_data['ratio'] is not None:
            ratio = float(form.cleaned_data['ratio'])
        if form.cleaned_data['minimum'] is not None:
            minimum = int(form.cleaned_data['minimum'])
        if form.cleaned_data['type'] == 'binary':
            binary = True
    usage_addons, usage_total = compat_stats(
        request, version, minimum, ratio, binary)

    return render(request, 'zadmin/compat.html', {
        'form': form, 'usage_addons': usage_addons,
        'usage_total': usage_total})


def compat_stats(request, version, minimum, ratio, binary):
    # Get the list of add-ons for usage stats.
    # Show add-ons marked as incompatible with this current version having
    # greater than 10 incompatible reports and whose average exceeds 80%.
    version_int = str(vint(version))
    prefix = 'works.%s' % version_int
    fields_to_retrieve = (
        'guid', 'slug', 'name', 'current_version', 'max_version', 'works',
        'usage', 'has_override', 'overrides', 'id')

    qs = (AppCompat.search()
          .filter(**{'%s.failure__gt' % prefix: minimum,
                     '%s.failure_ratio__gt' % prefix: ratio,
                     'support.max__gte': 0})
          .order_by('-%s.failure_ratio' % prefix,
                    '-%s.total' % prefix)
          .values_dict(*fields_to_retrieve))

    if binary is not None:
        qs = qs.filter(binary=binary)
    addons = amo.utils.paginate(request, qs)

    for obj in addons.object_list:
        obj['works'] = obj['works'].get(version_int, {})
        # Get all overrides for this add-on.
        obj['overrides'] = CompatOverride.objects.filter(addon__id=obj['id'])
        # Determine if there is an override for this current app version.
        obj['has_override'] = obj['overrides'].filter(
            _compat_ranges__min_app_version=version + 'a1').exists()
    return addons, CompatTotals.objects.get().total


@login_required
@json_view
def es_collections_json(request):
    app = request.GET.get('app', '')
    q = request.GET.get('q', '')
    qs = Collection.search()
    try:
        qs = qs.query(id__startswith=int(q))
    except ValueError:
        qs = qs.query(name__match=q)
    try:
        qs = qs.filter(app=int(app))
    except ValueError:
        pass
    data = []
    for c in qs[:7]:
        data.append({'id': c.id,
                     'name': unicode(c.name),
                     'all_personas': c.all_personas,
                     'url': c.get_url_path()})
    return data


@admin_required
@post_required
def featured_collection(request):
    try:
        pk = int(request.POST.get('collection', 0))
    except ValueError:
        pk = 0
    c = get_object_or_404(Collection, pk=pk)
    return render(request, 'zadmin/featured_collection.html',
                  dict(collection=c))


@admin_required
def features(request):
    form = FeaturedCollectionFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(commit=False)

        for obj in form.deleted_objects:
            obj.delete()

        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.features')
    return render(request, 'zadmin/features.html', dict(form=form))


@admin_required
def monthly_pick(request):
    form = MonthlyPickFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.monthly_pick')
    return render(request, 'zadmin/monthly_pick.html', dict(form=form))


@admin_required
def elastic(request):
    INDEX = settings.ES_INDEXES['default']
    es = search.get_es()

    indexes = set(settings.ES_INDEXES.values())
    es_mappings = {
        'addons': get_addons_mappings(),
        'addons_stats': get_stats_mappings(),
    }
    ctx = {
        'index': INDEX,
        'nodes': es.nodes.stats(),
        'health': es.cluster.health(),
        'state': es.cluster.state(),
        'mappings': [(index, es_mappings.get(index, {})) for index in indexes],
    }
    return render(request, 'zadmin/elastic.html', ctx)


@admin.site.admin_view
def mail(request):
    backend = DevEmailBackend()
    if request.method == 'POST':
        backend.clear()
        return redirect('zadmin.mail')
    return render(request, 'zadmin/mail.html', dict(mail=backend.view_all()))


@admin.site.admin_view
def email_devs(request):
    form = DevMailerForm(request.POST or None)
    preview = EmailPreviewTopic(topic='email-devs')
    if preview.filter().count():
        preview_csv = reverse('zadmin.email_preview_csv',
                              args=[preview.topic])
    else:
        preview_csv = None
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        qs = (
            AddonUser.objects.filter(
                role__in=(amo.AUTHOR_ROLE_DEV, amo.AUTHOR_ROLE_OWNER))
            .exclude(user__email=None)
            .filter(addon__status__in=amo.VALID_ADDON_STATUSES))

        if data['recipients'] == 'eula':
            qs = qs.exclude(addon__eula=None)
        elif data['recipients'] == 'sdk':
            qs = qs.exclude(addon__versions__files__jetpack_version=None)
        elif data['recipients'] == 'all_extensions':
            qs = qs.filter(addon__type=amo.ADDON_EXTENSION)
        elif data['recipients'] == 'depreliminary':
            addon_logs = AddonLog.objects.filter(
                activity_log__action=amo.LOG.PRELIMINARY_ADDON_MIGRATED.id,
                activity_log___details__contains='"email": true')
            addons = addon_logs.values_list('addon', flat=True)
            qs = qs.filter(addon__in=addons)
        else:
            raise NotImplementedError('If you want to support emailing other '
                                      'types of developers, do it here!')
        if data['preview_only']:
            # Clear out the last batch of previewed emails.
            preview.filter().delete()
        total = 0
        for emails in chunked(set(qs.values_list('user__email', flat=True)),
                              100):
            total += len(emails)
            tasks.admin_email.delay(emails, data['subject'], data['message'],
                                    preview_only=data['preview_only'],
                                    preview_topic=preview.topic)
        msg = 'Emails queued for delivery: %s' % total
        if data['preview_only']:
            msg = '%s (for preview only, emails not sent!)' % msg
        messages.success(request, msg)
        return redirect('zadmin.email_devs')
    return render(request, 'zadmin/email-devs.html',
                  dict(form=form, preview_csv=preview_csv))


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
            return redirect('zadmin.addon_manage', qs[0].id)
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
    cl = ChangeList(request, obj.model, [], [], [], [], obj.search_fields, [],
                    obj.list_max_show_all, limit, [], obj)
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

    return HttpResponseSendFile(request, upload.path,
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


@admin.site.admin_view
def memcache(request):
    form = YesImSure(request.POST or None)
    if form.is_valid() and form.cleaned_data['yes']:
        cache.clear()
        form = YesImSure()
        messages.success(request, 'Cache cleared')
    if cache._cache and hasattr(cache._cache, 'get_stats'):
        stats = cache._cache.get_stats()
    else:
        stats = []
    return render(request, 'zadmin/memcache.html',
                  {'form': form, 'stats': stats})


@admin.site.admin_view
def site_events(request, event_id=None):
    event = get_object_or_404(SiteEvent, pk=event_id) if event_id else None
    data = request.POST or None

    if event:
        form = SiteEventForm(data, instance=event)
    else:
        form = SiteEventForm(data)

    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('zadmin.site_events')
    pager = amo.utils.paginate(request, SiteEvent.objects.all(), 30)
    events = pager.object_list
    return render(request, 'zadmin/site_events.html', {
        'form': form, 'events': events})


@admin.site.admin_view
def delete_site_event(request, event_id):
    event = get_object_or_404(SiteEvent, pk=event_id)
    event.delete()
    return redirect('zadmin.site_events')
