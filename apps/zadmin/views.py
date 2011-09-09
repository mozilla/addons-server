import csv
import json
from datetime import datetime
from decimal import Decimal
from urlparse import urlparse

from django import http
# I'm so glad we named a function in here settings...
from django.conf import settings as site_settings
from django.contrib import admin
from django.db.models.loading import cache as app_cache
from django.shortcuts import redirect, get_object_or_404
from django.utils.encoding import smart_str
from django.views import debug
from django.views.decorators.cache import never_cache

import commonware.log
import elasticutils
import jinja2
import jingo
from hera.contrib.django_forms import FlushForm
from hera.contrib.django_utils import get_hera, flush_urls
from tower import ugettext as _

import amo.mail
import amo.models
import amo.tasks
import addons.search
import addons.cron
import bandwagon.cron
import files.tasks
import files.utils
import users.cron
from amo import messages, get_user
from amo.decorators import login_required, json_view, post_required
from amo.urlresolvers import reverse
from amo.utils import chunked, sorted_groupby
from addons.models import Addon
from addons.utils import ReverseNameLookup
from bandwagon.models import Collection
from devhub.models import ActivityLog
from files.models import Approval, File
from versions.models import Version

from . import tasks
from .forms import (BulkValidationForm, FeaturedCollectionFormSet, NotifyForm,
                    OAuthConsumerForm, MonthlyPickFormSet)
from .models import ValidationJob, EmailPreviewTopic, ValidationJobTally

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

    settings_dict['WEBAPPS_RECEIPT_KEY'] = '********************'

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
    current = job.curr_max_version.version_int
    target = job.target_version.version_int
    addons = (Addon.objects.filter(
                        status__in=amo.VALID_STATUSES,
                        disabled_by_user=False,
                        versions__apps__application=job.application.id,
                        versions__apps__max__version_int__gte=current,
                        versions__apps__max__version_int__lt=target)
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


@login_required
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
def validation_tally_csv(request, job_id):
    resp = http.HttpResponse()
    resp['Content-Type'] = 'text/csv; charset=utf-8'
    resp['Content-Disposition'] = ('attachment; '
                                   'filename=validation_tally_%s.csv'
                                   % job_id)
    writer = csv.writer(resp)
    fields = ['message_id', 'message', 'long_message',
              'type', 'addons_affected']
    writer.writerow(fields)
    job = ValidationJobTally(job_id)
    for msg in job.get_messages():
        row = [msg.key, msg.message, msg.long_message, msg.type,
               msg.addons_affected]
        writer.writerow([smart_str(r, encoding='utf8', strings_only=True)
                         for r in row])
    return resp


@admin.site.admin_view
def jetpack(request):
    upgrader = files.utils.JetpackUpgrader()
    minver, maxver = upgrader.jetpack_versions()
    if request.method == 'POST':
        if 'minver' in request.POST:
            upgrader.jetpack_versions(request.POST['minver'],
                                      request.POST['maxver'])
        elif 'upgrade' in request.POST:
            if upgrader.version(maxver):
                start_upgrade(minver, maxver)
        elif 'cancel' in request.POST:
            upgrader.cancel()
        return redirect('zadmin.jetpack')

    jetpacks = files.utils.find_jetpacks(minver, maxver)
    groups = sorted_groupby(jetpacks, 'jetpack_version')
    by_version = dict((version, len(list(files))) for version, files in groups)
    return jingo.render(request, 'zadmin/jetpack.html',
                        dict(jetpacks=jetpacks, upgrader=upgrader,
                             by_version=by_version))


def start_upgrade(minver, maxver):
    jetpacks = files.utils.find_jetpacks(minver, maxver)
    ids = [f.id for f in jetpacks if f.needs_upgrade]
    log.info('Starting a jetpack upgrade to %s [%s files].'
             % (maxver, len(ids)))
    files.tasks.start_upgrade.delay(ids)


@login_required
@json_view
def es_collections_json(request):
    app = request.GET.get('app', '')
    q = request.GET.get('q', '')
    qs = Collection.search()
    try:
        qs = qs.query(id__startswith=int(q))
    except ValueError:
        qs = qs.query(name__text=q)
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


@post_required
@admin.site.admin_view
def featured_collection(request):
    try:
        pk = int(request.POST.get('collection', 0))
    except ValueError:
        pk = 0
    c = get_object_or_404(Collection, pk=pk)
    return jingo.render(request, 'zadmin/featured_collection.html',
                        dict(collection=c))


@admin.site.admin_view
def features(request):
    form = FeaturedCollectionFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(commit=False)
        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.features')
    return jingo.render(request, 'zadmin/features.html', dict(form=form))


@admin.site.admin_view
def monthly_pick(request):
    form = MonthlyPickFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.monthly_pick')
    return jingo.render(request, 'zadmin/monthly_pick.html', dict(form=form))


@admin.site.admin_view
def elastic(request):
    INDEX = site_settings.ES_INDEXES['default']
    es = elasticutils.get_es()
    mappings = {'addons': (addons.search.setup_mapping,
                           addons.cron.reindex_addons),
                'collections': (addons.search.setup_mapping,
                                bandwagon.cron.reindex_collections),
                'compat': (addons.search.setup_mapping, None),
                'users': (addons.search.setup_mapping,
                          users.cron.reindex_users),
               }
    if request.method == 'POST':
        if request.POST.get('reset') in mappings:
            name = request.POST['reset']
            es.delete_mapping(INDEX, name)
            if mappings[name][0]:
                mappings[name][0]()
            messages.info(request, 'Resetting %s.' % name)
        if request.POST.get('reindex') in mappings:
            name = request.POST['reindex']
            mappings[name][1]()
            messages.info(request, 'Reindexing %s.' % name)
        return redirect('zadmin.elastic')

    indexes = set(site_settings.ES_INDEXES.values())
    mappings = es.get_mapping(None, indexes)
    ctx = {
        'nodes': es.cluster_nodes(),
        'health': es.cluster_health(),
        'state': es.cluster_state(),
        'mappings': [(index, mappings.get(index, {})) for index in indexes],
    }
    return jingo.render(request, 'zadmin/elastic.html', ctx)


@admin.site.admin_view
def mail(request):
    backend = amo.mail.FakeEmailBackend()
    if request.method == 'POST':
        backend.clear()
        return redirect('zadmin.mail')
    return jingo.render(request, 'zadmin/mail.html',
                        dict(mail=backend.view_all()))


@admin.site.admin_view
def celery(request):
    if request.method == 'POST' and 'reset' in request.POST:
        amo.tasks.task_stats.clear()
        return redirect('zadmin.celery')

    pending, failures, totals = amo.tasks.task_stats.stats()
    ctx = dict(pending=pending, failures=failures, totals=totals,
               now=datetime.now())
    return jingo.render(request, 'zadmin/celery.html', ctx)


@admin.site.admin_view
def addon_name_blocklist(request):
    rn = ReverseNameLookup()
    addon = None
    if request.method == 'POST':
        rn.delete(rn.get(request.GET['addon']))
    if request.GET.get('addon'):
        id = rn.get(request.GET.get('addon'))
        if id:
            qs = Addon.objects.filter(id=id)
            addon = qs[0] if qs else None
    return jingo.render(request, 'zadmin/addon-name-blocklist.html',
                        dict(rn=rn, addon=addon))


@admin.site.admin_view
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return jingo.render(request, 'zadmin/index.html', {'log': log})


@admin.site.admin_view
def addon_search(request):
    ctx = {}
    if 'q' in request.GET:
        q = ctx['q'] = request.GET['q']
        if q.isdigit():
            qs = Addon.objects.filter(id=int(q))
        else:
            qs = Addon.search().query(name__text=q.lower())[:100]
        if len(qs) == 1:
            # Note this is a remora URL and should be removed.
            return redirect('/admin/addons?q=[%s]' % qs[0].id)
        ctx['addons'] = qs
    return jingo.render(request, 'zadmin/addon-search.html', ctx)


@admin.site.admin_view
def oauth_consumer_create(request):
    form = OAuthConsumerForm(request.POST or None)
    if form.is_valid():
        # Generate random codes and save.
        form.instance.user = request.user
        form.instance.generate_random_codes()
        return redirect('admin:piston_consumer_changelist')

    return jingo.render(request, 'zadmin/oauth-consumer-create.html',
                        {'form': form})


@never_cache
@json_view
def general_search(request, app_id, model_id):
    if not admin.site.has_permission(request):
        return http.HttpResponseForbidden()

    model = app_cache.get_model(app_id, model_id)
    if not model:
        return http.Http404()

    limit = 10
    obj = admin.site._registry[model]
    ChangeList = obj.get_changelist(request)
    # This is a hideous api, but uses the builtin admin search_fields API.
    # Expecting this to get replaced by ES so soon, that I'm not going to lose
    # too much sleep about it.
    cl = ChangeList(request, obj.model, [], [], [], [],
                    obj.search_fields, [], limit, [], obj)
    qs = cl.get_query_set()
    # Override search_fields_response on the ModelAdmin object
    # if you'd like to pass something else back to the front end.
    lookup = getattr(obj, 'search_fields_response', None)
    return [{'value':o.pk, 'label':getattr(o, lookup) if lookup else str(o)}
            for o in qs[:limit]]
