import csv
import json
import os
from decimal import Decimal
from urlparse import urlparse

from django import http
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.db.models.loading import cache as app_cache
from django.shortcuts import get_object_or_404, redirect
from django.utils.encoding import smart_str
from django.views import debug
from django.views.decorators.cache import never_cache

import commonware.log
import elasticutils.contrib.django as elasticutils
import jinja2
import jingo
from hera.contrib.django_forms import FlushForm
from hera.contrib.django_utils import get_hera, flush_urls
from tower import ugettext as _

import amo
from addons.cron import reindex_addons, reindex_apps
from addons.search import setup_mapping
from addons.decorators import addon_view
from addons.models import Addon, AddonUser, CompatOverride
from amo import messages, get_user
from amo.decorators import (any_permission_required, json_view, login_required,
                            post_required)
from amo.mail import FakeEmailBackend
from amo.urlresolvers import reverse
from amo.utils import chunked, create_es_index_if_missing, sorted_groupby
from bandwagon.cron import reindex_collections
from bandwagon.models import Collection
from compat.cron import compatibility_report
from compat.models import AppCompat, CompatTotals
from devhub.models import ActivityLog
from files.models import Approval, File
from files.tasks import start_upgrade as start_upgrade_task
from files.utils import find_jetpacks, JetpackUpgrader
from stats.cron import index_latest_stats
from stats.search import setup_indexes
from users.cron import reindex_users
from versions.compare import version_int as vint
from versions.models import Version
from zadmin.forms import GenerateErrorForm, SiteEventForm
from zadmin.models import SiteEvent

from . import tasks
from .decorators import admin_required
from .forms import (AddonStatusForm, BulkValidationForm, CompatForm,
                    DevMailerForm, FeaturedCollectionFormSet, FileFormSet,
                    JetpackUpgradeForm, MonthlyPickFormSet, NotifyForm,
                    OAuthConsumerForm, YesImSure)
from .models import EmailPreviewTopic, ValidationJob, ValidationJobTally

log = commonware.log.getLogger('z.zadmin')

# This causes AMO problems if inapp gets imported. Then cache machine tries
# to query it to see if it exists.
if settings.MARKETPLACE and settings.IN_TEST_SUITE:
    from mkt.stats.cron import index_latest_mkt_stats, index_mkt_stats
    from mkt.stats.search import setup_mkt_indexes
else:
    index_latest_mkt_stats, index_mkt_stats = None, None
    setup_mkt_indexes = None


@admin_required(reviewers=True)
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
    form = FlushForm(initial={'flushprefix': settings.SITE_URL})

    boxes = []
    configured = False  # Default to not showing the form.
    for i in settings.HERA:
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


@admin_required
def show_settings(request):
    settings_dict = debug.get_safe_settings()

    # sigh
    settings_dict['HERA'] = []
    for i in settings.HERA:
        settings_dict['HERA'].append(debug.cleanse_setting('HERA', i))

    # Retain this so that legacy PAYPAL_CGI_AUTH variables in settings_local
    # are not exposed.
    for i in ['PAYPAL_EMBEDDED_AUTH', 'PAYPAL_CGI_AUTH']:
        settings_dict[i] = debug.cleanse_setting(i,
                                                 getattr(settings, i, {}))

    settings_dict['WEBAPPS_RECEIPT_KEY'] = '********************'

    return jingo.render(request, 'zadmin/settings.html',
                        {'settings_dict': settings_dict})


@admin_required
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


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
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
                           # Exclude lang packs and themes.
                           .exclude(type__in=[amo.ADDON_LPAPP,
                                              amo.ADDON_THEME])
                           .no_transforms().values_list("pk", flat=True)
                           .distinct())
    for pks in chunked(addons, 100):
        tasks.add_validation_jobs.delay(pks, job.pk)


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
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


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
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


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
@post_required
@json_view
def notify_syntax(request):
    notify_form = NotifyForm(request.POST)
    if not notify_form.is_valid():
        return {'valid': False, 'error': notify_form.errors['text'][0]}
    else:
        return {'valid': True, 'error': None}


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
@post_required
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


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
@post_required
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


@any_permission_required([('Admin', '%'),
                          ('BulkValidationAdminTools', 'View')])
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


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
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
    keys = ['key', 'message', 'long_message', 'type', 'addons_affected']
    for msg in job.get_messages():
        writer.writerow([smart_str(msg[k], encoding='utf8', strings_only=True)
                         for k in keys])
    return resp


@admin.site.admin_view
def jetpack(request):
    upgrader = JetpackUpgrader()
    minver, maxver = upgrader.jetpack_versions()
    form = JetpackUpgradeForm(request.POST)
    if request.method == 'POST':
        if form.is_valid():
            if 'minver' in request.POST:
                data = form.cleaned_data
                upgrader.jetpack_versions(data['minver'], data['maxver'])
            elif 'upgrade' in request.POST:
                if upgrader.version(maxver):
                    start_upgrade(minver, maxver)
            elif 'cancel' in request.POST:
                upgrader.cancel()
            return redirect('zadmin.jetpack')
        else:
            messages.error(request, form.errors.as_text())

    jetpacks = find_jetpacks(minver, maxver, from_builder_only=True)

    upgrading = upgrader.version()    # Current Jetpack version upgrading to.
    repack_status = upgrader.files()  # The files being repacked.

    show = request.GET.get('show', upgrading or minver)
    subset = filter(lambda f: not f.needs_upgrade and
                              f.jetpack_version == show, jetpacks)
    need_upgrade = filter(lambda f: f.needs_upgrade, jetpacks)
    repacked = []

    if upgrading:
        # Group the repacked files by status for this Jetpack upgrade.
        grouped_files = sorted_groupby(repack_status.values(),
                                       key=lambda f: f['status'])
        for group, rows in grouped_files:
            rows = sorted(list(rows), key=lambda f: f['file'])
            for idx, row in enumerate(rows):
                rows[idx]['file'] = File.objects.get(id=row['file'])
            repacked.append((group, rows))

    groups = sorted_groupby(jetpacks, 'jetpack_version')
    by_version = dict((version, len(list(files))) for version, files in groups)
    return jingo.render(request, 'zadmin/jetpack.html',
                        dict(form=form, upgrader=upgrader,
                             by_version=by_version, upgrading=upgrading,
                             need_upgrade=need_upgrade, subset=subset,
                             show=show, repacked=repacked,
                             repack_status=repack_status))


def start_upgrade(minver, maxver):
    jetpacks = find_jetpacks(minver, maxver, from_builder_only=True)
    ids = [f.id for f in jetpacks if f.needs_upgrade]
    log.info('Starting a jetpack upgrade to %s [%s files].'
             % (maxver, len(ids)))
    start_upgrade_task.delay(ids, sdk_version=maxver)


def jetpack_resend(request, file_id):
    maxver = JetpackUpgrader().version()
    log.info('Starting a jetpack upgrade to %s [1 file].' % maxver)
    start_upgrade_task.delay([file_id], sdk_version=maxver)
    return redirect('zadmin.jetpack')


@admin_required
def compat(request):
    APP = amo.FIREFOX
    VER = settings.COMPAT[0]['main']  # Default: latest Firefox version.
    minimum = 10
    ratio = .8
    binary = None

    # Expected usage:
    #     For Firefox 8.0 reports:      ?appver=1-8.0
    #     For over 70% incompatibility: ?appver=1-8.0&ratio=0.7
    #     For binary-only add-ons:      ?appver=1-8.0&type=binary
    initial = {'appver': '%s-%s' % (APP.id, VER), 'minimum': minimum,
               'ratio': ratio, 'type': 'all'}
    initial.update(request.GET.items())

    form = CompatForm(initial)
    if request.GET and form.is_valid():
        APP, VER = form.cleaned_data['appver'].split('-')
        APP = amo.APP_IDS[int(APP)]
        if form.cleaned_data['ratio'] is not None:
            ratio = float(form.cleaned_data['ratio'])
        if form.cleaned_data['minimum'] is not None:
            minimum = int(form.cleaned_data['minimum'])
        if form.cleaned_data['type'] == 'binary':
            binary = True

    app, ver = str(APP.id), VER
    usage_addons, usage_total = compat_stats(request, app, ver, minimum, ratio,
                                             binary)

    return jingo.render(request, 'zadmin/compat.html', {
        'app': APP,
        'version': VER,
        'form': form,
        'usage_addons': usage_addons,
        'usage_total': usage_total,
    })


def compat_stats(request, app, ver, minimum, ratio, binary):
    # Get the list of add-ons for usage stats.
    # Show add-ons marked as incompatible with this current version having
    # greater than 10 incompatible reports and whose average exceeds 80%.
    ver_int = str(vint(ver))
    prefix = 'works.%s.%s' % (app, ver_int)
    qs = (AppCompat.search()
          .filter(**{'%s.failure__gt' % prefix: minimum,
                     '%s.failure_ratio__gt' % prefix: ratio,
                     'support.%s.max__gte' % app: 0})
          .order_by('-%s.failure_ratio' % prefix,
                    '-%s.total' % prefix)
          .values_dict())
    if binary is not None:
        qs = qs.filter(binary=binary)
    addons = amo.utils.paginate(request, qs)
    for obj in addons.object_list:
        obj['usage'] = obj['usage'][app]
        obj['max_version'] = obj['max_version'][app]
        obj['works'] = obj['works'][app].get(ver_int, {})
        # Get all overrides for this add-on.
        obj['overrides'] = CompatOverride.objects.filter(addon__id=obj['id'])
        # Determine if there is an override for this current app version.
        obj['has_override'] = obj['overrides'].filter(
            _compat_ranges__min_app_version=ver + 'a1').exists()
    return addons, CompatTotals.objects.get(app=app).total


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


@admin_required
@post_required
def featured_collection(request):
    try:
        pk = int(request.POST.get('collection', 0))
    except ValueError:
        pk = 0
    c = get_object_or_404(Collection, pk=pk)
    return jingo.render(request, 'zadmin/featured_collection.html',
                        dict(collection=c))


@admin_required
def features(request):
    form = FeaturedCollectionFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(commit=False)
        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.features')
    return jingo.render(request, 'zadmin/features.html', dict(form=form))


@admin_required
def monthly_pick(request):
    form = MonthlyPickFormSet(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Changes successfully saved.')
        return redirect('zadmin.monthly_pick')
    return jingo.render(request, 'zadmin/monthly_pick.html', dict(form=form))


@admin.site.admin_view
def elastic(request):
    INDEX = settings.ES_INDEXES['default']
    es = elasticutils.get_es()
    mappings = {'addons': reindex_addons,
                'apps': reindex_apps,
                'collections': reindex_collections,
                'compat': compatibility_report,
                'users': reindex_users,
                'stats_latest': index_latest_stats,
                'mkt_stats': index_mkt_stats,
                'mkt_stats_latest': index_latest_mkt_stats}
    if request.method == 'POST':
        if request.POST.get('recreate'):
            es.delete_index_if_exists(INDEX)
            # We must set up the mappings before we create the index again.
            setup_mapping()
            setup_indexes()
            setup_mkt_indexes()
            create_es_index_if_missing(INDEX)
            messages.info(request, 'Deleting %s index.' % INDEX)
        if request.POST.get('reindex') in mappings:
            name = request.POST['reindex']
            # Reindex.
            if mappings.get(name):
                mappings[name]()
            messages.info(request, 'Reindexing %s.' % name)
        return redirect('zadmin.elastic')

    indexes = set(settings.ES_INDEXES.values())
    es_mappings = es.get_mapping(None, indexes)
    ctx = {
        'index': INDEX,
        'nodes': es.cluster_nodes(),
        'health': es.cluster_health(),
        'state': es.cluster_state(),
        'mappings': [(index, es_mappings.get(index, {})) for index in indexes],
        'choices': mappings,
    }
    return jingo.render(request, 'zadmin/elastic.html', ctx)


@admin.site.admin_view
def mail(request):
    backend = FakeEmailBackend()
    if request.method == 'POST':
        backend.clear()
        return redirect('zadmin.mail')
    return jingo.render(request, 'zadmin/mail.html',
                        dict(mail=backend.view_all()))


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
        listed = amo.LISTED_STATUSES
        qs = (AddonUser.objects.filter(role__in=(amo.AUTHOR_ROLE_DEV,
                                                 amo.AUTHOR_ROLE_OWNER),
                                       addon__status__in=listed)
                               .exclude(user__email=None))
        if data['recipients'] == 'eula':
            qs = qs.exclude(addon__eula=None)
        elif data['recipients'] == 'payments':
            qs = qs.filter(addon__type=amo.ADDON_WEBAPP)
            qs = qs.exclude(addon__paypal_id=None)
            qs = qs.exclude(addon__premium_type__in=(amo.ADDON_FREE,
                                                     amo.ADDON_OTHER_INAPP))
        elif data['recipients'] == 'sdk':
            qs = qs.exclude(addon__versions__files__jetpack_version=None)
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
    return jingo.render(request, 'zadmin/email-devs.html',
                        dict(form=form, preview_csv=preview_csv))


@any_permission_required([('Admin', '%'),
                          ('AdminTools', 'View'),
                          ('ReviewerAdminTools', 'View'),
                          ('BulkValidationAdminTools', 'View')])
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return jingo.render(request, 'zadmin/index.html', {'log': log})


@admin_required(reviewers=True)
def addon_search(request):
    ctx = {}
    if 'q' in request.GET:
        q = ctx['q'] = request.GET['q']
        if q.isdigit():
            qs = Addon.objects.filter(id=int(q))
        else:
            qs = (Addon.search()
                       .query(name__text=q.lower())
                       .filter(type__in=amo.MARKETPLACE_TYPES if
                                        settings.MARKETPLACE else
                                        amo.ADDON_ADMIN_SEARCH_TYPES)[:100])
        if len(qs) == 1:
            return redirect('zadmin.addon_manage', qs[0].id)
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
    cl = ChangeList(request, obj.model, [], [], [], [], obj.search_fields, [],
                    obj.list_max_show_all, limit, [], obj)
    qs = cl.get_query_set(request)
    # Override search_fields_response on the ModelAdmin object
    # if you'd like to pass something else back to the front end.
    lookup = getattr(obj, 'search_fields_response', None)
    return [{'value':o.pk, 'label':getattr(o, lookup) if lookup else str(o)}
            for o in qs[:limit]]


@admin_required(reviewers=True)
@addon_view
def addon_manage(request, addon):

    form = AddonStatusForm(request.POST or None, instance=addon)
    pager = amo.utils.paginate(request, addon.versions.all(), 30)
    # A list coercion so this doesn't result in a subquery with a LIMIT which
    # MySQL doesn't support (at this time).
    versions = list(pager.object_list)
    files = File.objects.filter(version__in=versions).select_related('version')
    formset = FileFormSet(request.POST or None, queryset=files)

    if form.is_valid() and formset.is_valid():
        if 'status' in form.changed_data:
            amo.log(amo.LOG.CHANGE_STATUS, addon, form.cleaned_data['status'])
            log.info('Addon "%s" status changed to: %s' % (
                addon.slug, form.cleaned_data['status']))
            form.save()
        if 'highest_status' in form.changed_data:
            log.info('Addon "%s" highest status changed to: %s' % (
                addon.slug, form.cleaned_data['highest_status']))
            form.save()

        if 'outstanding' in form.changed_data:
            log.info('Addon "%s" changed to%s outstanding' % (addon.slug,
                     '' if form.cleaned_data['outstanding'] else ' not'))
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

    return jingo.render(request, 'zadmin/addon_manage.html', {
        'addon': addon,
        'pager': pager,
        'versions': versions,
        'form': form,
        'formset': formset,
        'form_map': form_map,
        'file_map': file_map,
    })


@admin.site.admin_view
@post_required
@json_view
def recalc_hash(request, file_id):

    file = get_object_or_404(File, pk=file_id)
    file.size = int(max(1, round(os.path.getsize(file.file_path) / 1024, 0)))
    file.hash = file.generate_hash()
    file.save()

    log.info('Recalculated hash for file ID %d' % file.id)
    messages.success(request,
                     'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}


@admin.site.admin_view
def memcache(request):
    form = YesImSure(request.POST or None)
    if form.is_valid():
        cache.clear()
        form = YesImSure()
        messages.success(request, 'Cache cleared')
    if cache._cache and hasattr(cache._cache, 'get_stats'):
        stats = cache._cache.get_stats()
    else:
        stats = []
    return jingo.render(request, 'zadmin/memcache.html',
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
    return jingo.render(request, 'zadmin/site_events.html', {
        'form': form,
        'events': events,
    })


@admin.site.admin_view
def delete_site_event(request, event_id):
    event = get_object_or_404(SiteEvent, pk=event_id)
    event.delete()
    return redirect('zadmin.site_events')


@admin_required
def generate_error(request):
    form = GenerateErrorForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.explode()
    return jingo.render(request, 'zadmin/generate-error.html', {'form': form})
