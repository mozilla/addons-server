import csv
import json
from decimal import Decimal

from django.apps import apps
from django import http
from django.db import transaction
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import ugettext_lazy as _
from django.utils.html import format_html
from django.views import debug
from django.views.decorators.cache import never_cache

import olympia.core.logger
import django_tables2 as tables

from olympia import amo, core
from olympia.amo import search
from olympia.activity.models import ActivityLog, AddonLog
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, AddonUser, CompatOverride
from olympia.amo import messages
from olympia.amo.decorators import (
    any_permission_required, json_view, login_required, post_required)
from olympia.amo.mail import DevEmailBackend
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, chunked, render
from olympia.bandwagon.models import Collection
from olympia.compat import FIREFOX_COMPAT
from olympia.compat.models import AppCompat, CompatTotals
from olympia.editors.utils import ItemStateTable
from olympia.files.models import File, FileUpload
from olympia.search.indexers import get_mappings as get_addons_mappings
from olympia.stats.search import get_mappings as get_stats_mappings
from olympia.users.models import UserProfile
from olympia.versions.compare import version_int as vint
from olympia.versions.models import Version
from olympia.zadmin.forms import SiteEventForm
from olympia.zadmin.models import SiteEvent, ValidationResult

from . import tasks
from .decorators import admin_required
from .forms import (
    AddonStatusForm, BulkValidationForm, CompatForm, DevMailerForm,
    FeaturedCollectionFormSet, FileFormSet, MonthlyPickFormSet, NotifyForm,
    YesImSure)
from .models import (
    EmailPreviewTopic, ValidationJob, ValidationResultMessage,
    ValidationResultAffectedAddon)

log = olympia.core.logger.getLogger('z.zadmin')


@admin_required(reviewers=True)
def langpacks(request):
    if request.method == 'POST':
        try:
            tasks.fetch_langpacks.delay(request.POST['path'])
        except ValueError:
            messages.error(request, 'Invalid language pack sub-path provided.')

        return redirect('zadmin.langpacks')

    addons = (Addon.objects.no_cache()
              .filter(addonuser__user__email=settings.LANGPACK_OWNER_EMAIL,
                      type=amo.ADDON_LPAPP)
              .order_by('name'))

    data = {'addons': addons, 'base_url': settings.LANGPACK_DOWNLOAD_BASE,
            'default_path': settings.LANGPACK_PATH_DEFAULT % (
                'firefox', amo.FIREFOX.latest_version)}

    return render(request, 'zadmin/langpack_update.html', data)


@admin_required
def show_settings(request):
    settings_dict = debug.get_safe_settings()

    # Retain this so that legacy PAYPAL_CGI_AUTH variables in local settings
    # are not exposed.
    for i in ['PAYPAL_EMBEDDED_AUTH', 'PAYPAL_CGI_AUTH',
              'GOOGLE_ANALYTICS_CREDENTIALS']:
        settings_dict[i] = debug.cleanse_setting(i,
                                                 getattr(settings, i, {}))

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
    f = BulkValidationForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
def validation(request, form=None):
    if not form:
        form = BulkValidationForm()
    jobs = ValidationJob.objects.order_by('-created')
    return render(request, 'zadmin/validation.html',
                  {'form': form,
                   'notify_form': NotifyForm(text='validation'),
                   'validation_jobs': jobs})


def find_files(job):
    # This is a first pass, we know we don't want any addons in the states
    # STATUS_NULL and STATUS_DISABLED.
    current = job.curr_max_version.version_int
    target = job.target_version.version_int
    addons = (
        Addon.objects.filter(status__in=amo.VALID_ADDON_STATUSES,
                             disabled_by_user=False,
                             versions__apps__application=job.application,
                             versions__apps__max__version_int__gte=current,
                             versions__apps__max__version_int__lt=target)
        # Exclude lang packs and themes.
        .exclude(type__in=[amo.ADDON_LPAPP,
                           amo.ADDON_THEME])
        # Exclude WebExtensions (see #1499).
        .exclude(versions__files__is_webextension=True)
        .no_transforms().values_list("pk", flat=True)
        .distinct())
    for pks in chunked(addons, 100):
        tasks.add_validation_jobs.delay(pks, job.pk)


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
@transaction.non_atomic_requests
def start_validation(request):
    # FIXME: `@transaction.non_atomic_requests` is a workaround for an issue
    # that might exist elsewhere too. The view is wrapped in a transaction
    # by default and because of that tasks being started in this view
    # won't see the `ValidationJob` object created.
    form = BulkValidationForm(request.POST)
    if form.is_valid():
        job = form.save(commit=False)
        job.creator = core.get_user()
        job.save()
        find_files(job)
        return redirect(reverse('zadmin.validation'))
    else:
        return validation(request, form=form)


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
@post_required
@json_view
def job_status(request):
    ids = json.loads(request.POST['job_ids'])
    jobs = ValidationJob.objects.filter(pk__in=ids)
    all_stats = {}
    for job in jobs:
        status = job.stats
        for k, v in status.items():
            if isinstance(v, Decimal):
                status[k] = str(v)
        all_stats[job.pk] = status
    return all_stats


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
@post_required
@json_view
def notify_syntax(request):
    notify_form = NotifyForm(request.POST)
    if not notify_form.is_valid():
        return {'valid': False, 'error': notify_form.errors['text'][0]}
    else:
        return {'valid': True, 'error': None}


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
@post_required
def notify(request, job):
    job = get_object_or_404(ValidationJob, pk=job)
    notify_form = NotifyForm(request.POST, text='validation')

    if not notify_form.is_valid():
        messages.error(request, notify_form)
    else:
        tasks.notify_compatibility.delay(job, notify_form.cleaned_data)

    return redirect(reverse('zadmin.validation'))


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
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


class BulkValidationResultTable(ItemStateTable, tables.Table):
    message_id = tables.Column(verbose_name=_('Message ID'))
    message = tables.Column(verbose_name=_('Message'))
    compat_type = tables.Column(verbose_name=_('Compat Type'))
    addons_affected = tables.Column(verbose_name=_('Addons Affected'))

    def render_message_id(self, record):
        detail_url = reverse(
            'zadmin.validation_summary_detail',
            args=(record.validation_job.pk, record.id))
        return format_html(
            u'<a href="{0}">{1}</a>', detail_url, record.message_id)


class BulkValidationAffectedAddonsTable(ItemStateTable, tables.Table):
    addon = tables.Column(verbose_name=_('Addon'))
    validation_link = tables.Column(
        verbose_name=_('Validation Result'),
        empty_values=())

    def __init__(self, *args, **kwargs):
        self.results = kwargs.pop('results')
        super(BulkValidationAffectedAddonsTable, self).__init__(
            *args, **kwargs)

    def render_addon(self, record):
        addon = record.addon
        detail_url = reverse('addons.detail', args=(addon.pk,))
        return format_html(u'<a href="{0}">{1}</a>', detail_url, addon.name)

    def render_validation_link(self, record):
        results = [
            (result.pk, reverse(
                'devhub.bulk_compat_result',
                args=(result.file.version.addon_id, result.pk)))
            for result in self.results
            if result.file.version.addon_id == record.addon.id]

        return ', '.join(
            format_html(u'<a href="{0}">{1}</a>', result[1], result[0])
            for result in results)


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
def validation_summary(request, job_id):
    messages = ValidationResultMessage.objects.filter(validation_job=job_id)
    order_by = request.GET.get('sort', 'message_id')

    table = BulkValidationResultTable(data=messages, order_by=order_by)

    page = amo.utils.paginate(request, table.rows, per_page=25)
    table.set_page(page)
    return render(request, 'zadmin/validation_summary.html',
                  {'table': table, 'page': page})


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
def validation_summary_affected_addons(request, job_id, message_id):
    affected_addons = list(
        ValidationResultAffectedAddon.objects
        .filter(
            validation_result_message=message_id,
            validation_result_message__validation_job=job_id))

    # Get rid of duplicates
    addon_ids = set()

    for affected_addon in affected_addons:
        if affected_addon.addon_id in addon_ids:
            affected_addons.remove(affected_addon)
            continue

        addon_ids.add(affected_addon.addon_id)

    order_by = request.GET.get('sort', 'addon')

    results = (
        ValidationResult.objects
        .select_related('file__version')
        .filter(validation_job=job_id,
                file__version__addon__in=addon_ids))

    table = BulkValidationAffectedAddonsTable(
        results=results,
        data=affected_addons, order_by=order_by)

    page = amo.utils.paginate(request, table.rows, per_page=25)
    table.set_page(page)

    message = ValidationResultMessage.objects.filter(
        validation_job=job_id, id=message_id)[0]
    return render(request, 'zadmin/validation_summary.html',
                  {'table': table,
                   'page': page,
                   'message_id': message.message_id,
                   'message': message.message})


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


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.ADMIN_TOOLS_VIEW,
                          amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW])
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return render(request, 'zadmin/index.html', {'log': log})


@admin_required(reviewers=True)
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


@admin_required(reviewers=True)
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


@admin_required(reviewers=True)
def download_file(request, uuid):
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


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.MAILING_LISTS_VIEW])
def export_email_addresses(request):
    return render(request, 'zadmin/export_button.html', {})


@any_permission_required([amo.permissions.ADMIN,
                          amo.permissions.MAILING_LISTS_VIEW])
def email_addresses_file(request):
    resp = http.HttpResponse()
    resp['Content-Type'] = 'text/plain; charset=utf-8'
    resp['Content-Disposition'] = ('attachment; '
                                   'filename=amo_optin_emails.txt')
    emails = (UserProfile.objects.filter(notifications__notification_id=13,
                                         notifications__enabled=1)
              .values_list('email', flat=True))
    for e in emails:
        if e is not None:
            resp.write(e + '\n')
    return resp
