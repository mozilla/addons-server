import csv
from itertools import groupby
from urlparse import urlparse

from django import http
# I'm so glad we named a function in here settings...
from django.conf import settings as site_settings
from django.contrib import admin
from django.shortcuts import redirect, get_object_or_404
from django.views import debug

import commonware.log
import elasticutils
import jinja2
import jingo
from hera.contrib.django_forms import FlushForm
from hera.contrib.django_utils import get_hera, flush_urls
from tower import ugettext as _

from amo import messages
from amo import get_user
from amo.decorators import login_required, json_view, post_required
import amo.models
from amo.urlresolvers import reverse
from amo.utils import chunked
from addons.models import Addon
import files.tasks
import files.utils
from files.models import Approval, File
from versions.models import Version

from . import tasks
from .forms import BulkValidationForm, NotifyForm
from .models import ValidationJob, EmailPreviewTopic, Config

log = commonware.log.getLogger('z.zadmin')


@admin.site.admin_view
def flagged(request):
    addons = Addon.objects.filter(admin_review=True).order_by('-created')

    if request.method == 'POST':
        ids = map(int, request.POST.getlist('addon_id'))
        addons = list(addons)
        Addon.objects.filter(id__in=ids).update(admin_review=False)
        # The sql update doesn't invalidate anything, do it manually.
        invalid = [addon for addon in addons if addon.pk in ids]
        Addon.objects.invalidate(*invalid)
        return redirect('zadmin.flagged')

    sql = """SELECT {t}.* FROM {t} JOIN (
                SELECT addon_id, MAX(created) AS created
                FROM {t}
                GROUP BY addon_id) as J
             ON ({t}.addon_id = J.addon_id AND {t}.created = J.created)
             WHERE {t}.addon_id IN {ids}"""
    approvals_sql = sql + """
        AND (({t}.reviewtype = 'nominated' AND {t}.action = %s)
             OR ({t}.reviewtype = 'pending' AND {t}.action = %s))"""

    ids = '(%s)' % ', '.join(str(a.id) for a in addons)
    versions_sql = sql.format(t=Version._meta.db_table, ids=ids)
    approvals_sql = approvals_sql.format(t=Approval._meta.db_table, ids=ids)

    versions = dict((x.addon_id, x) for x in
                    Version.objects.raw(versions_sql))
    approvals = dict((x.addon_id, x) for x in
                     Approval.objects.raw(approvals_sql,
                                          [amo.STATUS_NOMINATED,
                                           amo.STATUS_PENDING]))

    for addon in addons:
        addon.version = versions.get(addon.id)
        addon.approval = approvals.get(addon.id)

    return jingo.render(request, 'zadmin/flagged_addon_list.html',
                        {'addons': addons})


@admin.site.admin_view
def hera(request):
    form = FlushForm(initial={'flushprefix': site_settings.SITE_URL})

    boxes = []
    configured = False  # Default to not showing the form.
    for i in site_settings.HERA:
        hera = get_hera(i)
        r = {'location': urlparse(i['LOCATION'])[1], 'stats': False}
        if hera:
            r['stats'] = hera.getGlobalCacheInfo()
            configured = True
        boxes.append(r)

    if not configured:
        messages.error(request, "Hera is not (or mis-)configured.")
        form = None

    if request.method == 'POST' and hera:
        form = FlushForm(request.POST)
        if form.is_valid():
            expressions = request.POST['flushlist'].splitlines()

            for url in expressions:
                num = flush_urls([url], request.POST['flushprefix'], True)
                msg = ("Flushed %d objects from front end cache for: %s"
                       % (len(num), url))
                log.info("[Hera] (user:%s) %s" % (request.user, msg))
                messages.success(request, msg)

    return jingo.render(request, 'zadmin/hera.html',
                        {'form': form, 'boxes': boxes})


@admin.site.admin_view
def settings(request):
    settings_dict = debug.get_safe_settings()

    # sigh
    settings_dict['HERA'] = []
    for i in site_settings.HERA:
        settings_dict['HERA'].append(debug.cleanse_setting('HERA', i))

    for i in ['PAYPAL_EMBEDDED_AUTH', 'PAYPAL_CGI_AUTH']:
        settings_dict[i] = debug.cleanse_setting(i, getattr(site_settings, i))

    return jingo.render(request, 'zadmin/settings.html',
                        {'settings_dict': settings_dict})


@admin.site.admin_view
def env(request):
    return http.HttpResponse(u'<pre>%s</pre>' % (jinja2.escape(request)))


@admin.site.admin_view
def fix_disabled_file(request):
    file_ = None
    if request.method == 'POST' and 'file' in request.POST:
        file_ = get_object_or_404(File, id=request.POST['file'])
        if 'confirm' in request.POST:
            file_.unhide_disabled_file()
            messages.success(request, 'We have done a great thing.')
            return redirect('zadmin.fix-disabled')
    return jingo.render(request, 'zadmin/fix-disabled.html',
                        {'file': file_,
                         'file_id': request.POST.get('file', '')})


@login_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application_id']
    f = BulkValidationForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@admin.site.admin_view
def validation(request, form=None):
    if not form:
        form = BulkValidationForm()
    jobs = ValidationJob.objects.order_by('-created')
    return jingo.render(request, 'zadmin/validation.html',
                        {'form': form,
                         'success_form': NotifyForm(text='success'),
                         'failure_form': NotifyForm(text='failure'),
                         'validation_jobs': jobs})


def find_files(job):
    # This is a first pass, we know we don't want any addons in the states
    # STATUS_NULL and STATUS_DISABLED.
    addons = (Addon.objects.filter(status__in=amo.VALID_STATUSES,
                                disabled_by_user=False,
                                versions__apps__application=job.application.id,
                                versions__apps__max=job.curr_max_version.id)
                           .no_transforms().values_list("pk", flat=True)
                           .distinct())
    for pks in chunked(addons, 100):
        tasks.add_validation_jobs.delay(pks, job.pk)


@admin.site.admin_view
def start_validation(request):
    form = BulkValidationForm(request.POST)
    if form.is_valid():
        job = form.save(commit=False)
        job.creator = get_user()
        job.save()
        find_files(job)
        return redirect(reverse('zadmin.validation'))
    else:
        return validation(request, form=form)


def completed_versions_dirty(job):
    """Given a job, calculate which unique versions could need updating."""
    return (Version.objects
                   .filter(files__validation_results__validation_job=job,
                           files__validation_results__errors=0,
                           files__validation_results__completed__isnull=False)
                   .values_list('pk', flat=True).distinct())


@post_required
@admin.site.admin_view
@json_view
def notify_syntax(request):
    notify_form = NotifyForm(request.POST)
    if not notify_form.is_valid():
        return {'valid': False, 'error': notify_form.errors['text'][0]}
    else:
        return {'valid': True, 'error': None}


@post_required
@admin.site.admin_view
def notify_failure(request, job):
    job = get_object_or_404(ValidationJob, pk=job)
    notify_form = NotifyForm(request.POST, text='failure')

    if not notify_form.is_valid():
        messages.error(request, notify_form)

    else:
        file_pks = job.result_failing().values_list('file_id', flat=True)
        for chunk in chunked(file_pks, 100):
            tasks.notify_failed.delay(chunk, job.pk, notify_form.cleaned_data)
        messages.success(request, _('Notifying authors task started.'))

    return redirect(reverse('zadmin.validation'))


@post_required
@admin.site.admin_view
def notify_success(request, job):
    job = get_object_or_404(ValidationJob, pk=job)
    notify_form = NotifyForm(request.POST, text='success')

    if not notify_form.is_valid():
        messages.error(request, notify_form.errors)

    else:
        versions = completed_versions_dirty(job)
        for chunk in chunked(versions, 100):
            tasks.notify_success.delay(chunk, job.pk, notify_form.cleaned_data)
        messages.success(request, _('Updating max version task and '
                                    'notifying authors started.'))

    return redirect(reverse('zadmin.validation'))


@admin.site.admin_view
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


@admin.site.admin_view
def jetpack(request):
    cfg = Config.objects.get(key='jetpack_version')
    upgrader = files.utils.JetpackUpgrader()
    if request.method == 'POST':
        if request.POST.get('jetpack_version'):
            cfg.value = request.POST['jetpack_version']
            cfg.save()
        elif 'upgrade' in request.POST:
            if upgrader.version(cfg.value):
                start_upgrade(cfg.value)
            else:
                print 'no more than one'
        elif 'cancel' in request.POST:
            upgrader.stop()
        return redirect('zadmin.jetpack')

    jetpacks = files.utils.find_jetpacks()
    groups = groupby(jetpacks, key=lambda f: f.jetpack_version)
    by_version = dict((version, len(list(files))) for version, files in groups)
    return jingo.render(request, 'zadmin/jetpack.html',
                        dict(cfg=cfg, jetpacks=jetpacks,
                             by_version=by_version))


@admin.site.admin_view
def elastic(request):
    es = elasticutils.get_es()
    return jingo.render(request, 'zadmin/elastic.html',
                        dict(nodes=es.cluster_nodes(),
                             health=es.cluster_health(),
                             state=es.cluster_state()))


def start_upgrade(version):
    jetpacks = files.utils.find_jetpacks()
    ids = [f.id for f in jetpacks if f.needs_upgrade]
    log.info('Starting a jetpack upgrade to %s [%s files].'
             % (version, len(ids)))
    files.tasks.start_upgrade.delay(version, ids)
