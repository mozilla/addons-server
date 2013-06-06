import collections
import datetime
import json
import os
import sys
import traceback
import urllib

from django import http
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.signals import post_save
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
import requests
from tower import ugettext as _

import amo
from abuse.models import AbuseReport
from access import acl
from addons.decorators import addon_view
from addons.models import AddonDeviceType, Persona, Version
from amo import messages
from amo.decorators import json_view, permission_required
from amo.helpers import absolutify
from amo.models import manual_order
from amo.urlresolvers import reverse
from amo.utils import (escape_all, HttpResponseSendFile, JSONEncoder, paginate,
                       smart_decode)
from devhub.models import ActivityLog, ActivityLogAttachment
from editors.forms import MOTDForm
from editors.models import (EditorSubscription, EscalationQueue, RereviewQueue,
                            ReviewerScore)
from editors.views import reviewer_required
from files.models import File
from lib.crypto.packaged import SigningError
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
from translations.query import order_by_translation
from users.models import UserProfile
from zadmin.models import set_config, unmemoized_get_config

from mkt.reviewers.utils import AppsReviewing, clean_sort_param
from mkt.search.forms import ApiSearchForm
from mkt.site.helpers import product_as_dict
from mkt.webapps.models import Webapp

from . import forms
from .models import AppCannedResponse


QUEUE_PER_PAGE = 100
log = commonware.log.getLogger('z.reviewers')


@reviewer_required
def home(request):
    durations = (('new', _('New Apps (Under 5 days)')),
                 ('med', _('Passable (5 to 10 days)')),
                 ('old', _('Overdue (Over 10 days)')))

    progress, percentage = _progress()

    data = context(
        reviews_total=ActivityLog.objects.total_reviews(webapp=True)[:5],
        reviews_monthly=ActivityLog.objects.monthly_reviews(webapp=True)[:5],
        #new_editors=EventLog.new_editors(),  # Bug 747035
        #eventlog=ActivityLog.objects.editor_events()[:6],  # Bug 746755
        progress=progress,
        percentage=percentage,
        durations=durations
    )
    return jingo.render(request, 'reviewers/home.html', data)


def queue_counts():
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)

    counts = {
        'pending': Webapp.uncached
                         .exclude(id__in=excluded_ids)
                         .filter(type=amo.ADDON_WEBAPP,
                                 disabled_by_user=False,
                                 status=amo.STATUS_PENDING)
                         .count(),
        'rereview': RereviewQueue.uncached
                                 .exclude(addon__in=excluded_ids)
                                 .filter(addon__disabled_by_user=False)
                                 .count(),
        # This will work as long as we disable files of existing unreviewed
        # versions when a new version is uploaded.
        'updates': File.uncached
                       .exclude(version__addon__id__in=excluded_ids)
                       .filter(version__addon__type=amo.ADDON_WEBAPP,
                               version__addon__disabled_by_user=False,
                               version__addon__is_packaged=True,
                               version__addon__status=amo.STATUS_PUBLIC,
                               version__deleted=False,
                               status=amo.STATUS_PENDING)
                       .count(),
        'escalated': EscalationQueue.uncached
                                    .filter(addon__disabled_by_user=False)
                                    .count(),
        'moderated': Review.uncached.filter(addon__type=amo.ADDON_WEBAPP,
                                            reviewflag__isnull=False,
                                            editorreview=True)
                                    .count(),
        'themes': Persona.objects.no_cache()
                                 .filter(addon__status=amo.STATUS_PENDING)
                                 .count(),
    }
    rv = {}
    if isinstance(type, basestring):
        return counts[type]
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v
    return rv


def _progress():
    """Returns unreviewed apps progress.

    Return the number of apps still unreviewed for a given period of time and
    the percentage.
    """

    days_ago = lambda n: datetime.datetime.now() - datetime.timedelta(days=n)
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Webapp.uncached.exclude(id__in=excluded_ids)
                         .filter(status=amo.STATUS_PENDING,
                                 disabled_by_user=False))
    progress = {
        'new': qs.filter(created__gt=days_ago(5)).count(),
        'med': qs.filter(created__range=(days_ago(10), days_ago(5))).count(),
        'old': qs.filter(created__lt=days_ago(10)).count(),
        'week': qs.filter(created__gte=days_ago(7)).count(),
    }

    # Return the percent of (p)rogress out of (t)otal.
    pct = lambda p, t: (p / float(t)) * 100 if p > 0 else 0

    percentage = {}
    total = progress['new'] + progress['med'] + progress['old']
    percentage = {}
    for duration in ('new', 'med', 'old'):
        percentage[duration] = pct(progress[duration], total)

    return (progress, percentage)


def context(**kw):
    statuses = dict((k, unicode(v)) for k, v in amo.STATUS_CHOICES.items())
    ctx = dict(motd=unmemoized_get_config('mkt_reviewers_motd'),
               queue_counts=queue_counts(),
               search_url=reverse('api_dispatch_list', kwargs={
                   'api_name': 'apps', 'resource_name': 'search'}),
               statuses=statuses)
    ctx.update(kw)
    return ctx


def _review(request, addon, version):

    if (not settings.ALLOW_SELF_REVIEWS and
        not acl.action_allowed(request, 'Admin', '%') and
        addon.has_author(request.amo_user)):
        messages.warning(request, _('Self-reviews are not allowed.'))
        return redirect(reverse('reviewers.home'))

    if (addon.status == amo.STATUS_BLOCKED and
        not acl.action_allowed(request, 'Apps', 'ReviewEscalated')):
        messages.warning(
            request, _('Only senior reviewers can review blocklisted apps.'))
        return redirect(reverse('reviewers.home'))

    attachment_formset = forms.AttachmentFormSet(data=request.POST or None,
                                                 files=request.FILES or None,
                                                 prefix='attachment')
    form = forms.get_review_form(data=request.POST or None,
                                 files=request.FILES or None, request=request,
                                 addon=addon, version=version,
                                 attachment_formset=attachment_formset)
    queue_type = form.helper.review_type
    redirect_url = reverse('reviewers.apps.queue_%s' % queue_type)
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')

    forms_valid = lambda: form.is_valid() and attachment_formset.is_valid()
    if request.method == 'POST' and forms_valid():

        old_types = set(o.id for o in addon.device_types)
        new_types = set(form.cleaned_data.get('device_override'))

        if (form.cleaned_data.get('action') == 'public' and
            old_types != new_types):

            # The reviewer overrode the device types. We need to not publish
            # this app immediately.
            if addon.make_public == amo.PUBLIC_IMMEDIATELY:
                addon.update(make_public=amo.PUBLIC_WAIT)

            # And update the device types to what the reviewer set.
            AddonDeviceType.objects.filter(addon=addon).delete()
            for device in form.cleaned_data.get('device_override'):
                addon.addondevicetype_set.create(device_type=device)

            # Log that the reviewer changed the device types.
            added_devices = new_types - old_types
            removed_devices = old_types - new_types
            msg = _(u'Device(s) changed by reviewer: {0}').format(', '.join(
                [_(u'Added {0}').format(unicode(amo.DEVICE_TYPES[d].name))
                 for d in added_devices] +
                [_(u'Removed {0}').format(unicode(amo.DEVICE_TYPES[d].name))
                 for d in removed_devices]))
            amo.log(amo.LOG.REVIEW_DEVICE_OVERRIDE, addon,
                    addon.current_version, details={'comments': msg})

        form.helper.process()

        if form.cleaned_data.get('notify'):
            EditorSubscription.objects.get_or_create(user=request.amo_user,
                                                     addon=addon)

        messages.success(request, _('Review successfully processed.'))
        return redirect(redirect_url)

    canned = AppCannedResponse.objects.all()
    actions = form.helper.actions.items()

    try:
        show_diff = (addon.versions.exclude(id=version.id)
                                   .filter(files__isnull=False,
                                           created__lt=version.created,
                                           files__status=amo.STATUS_PUBLIC)
                                   .latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we should show a minimal form from.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    # We only allow the user to check/uncheck files for "pending"
    allow_unchecking_files = form.helper.review_type == "pending"

    versions = (Version.with_deleted.filter(addon=addon)
                                    .order_by('-created')
                                    .transform(Version.transformer_activity)
                                    .transform(Version.transformer))

    product_attrs = {
        'product': json.dumps(
            product_as_dict(request, addon, False, 'reviewer'),
            cls=JSONEncoder),
        'manifest_url': addon.manifest_url,
    }

    pager = paginate(request, versions, 10)

    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    ctx = context(version=version, product=addon, pager=pager,
                  num_pages=num_pages, count=count,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES, show_diff=show_diff,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal,
                  tab=queue_type, product_attrs=product_attrs,
                  attachment_formset=attachment_formset)

    return jingo.render(request, 'reviewers/review.html', ctx)


@transaction.commit_manually
@permission_required('Apps', 'Review')
@addon_view
def app_review(request, addon):
    version = addon.latest_version
    resp = None
    try:
        resp = _review(request, addon, version)
    except SigningError, exc:
        transaction.rollback()
        messages.error(request, 'Signing Error: %s' % exc)
        transaction.commit()
        return redirect(
            reverse('reviewers.apps.review', args=[addon.app_slug]))
    except Exception:
        transaction.rollback()
        raise
    else:
        transaction.commit()
        # Temp. reindex the addon now it's been committed.
        if not settings.IN_TEST_SUITE and request.method == 'POST':
            post_save.send(sender=Webapp, instance=addon, created=False)
            post_save.send(sender=Version, instance=version, created=False)
            transaction.commit()
        if resp:
            return resp
        raise


QueuedApp = collections.namedtuple('QueuedApp', 'app created')


def _queue(request, apps, tab, pager_processor=None):
    per_page = request.GET.get('per_page', QUEUE_PER_PAGE)
    pager = paginate(request, apps, per_page)

    return jingo.render(request, 'reviewers/queue.html', context(**{
        'addons': pager.object_list,
        'pager': pager,
        'tab': tab,
        'search_form': _get_search_form(request),
    }))


def _do_sort(request, qs, date_field='created'):
    """Column sorting logic based on request GET parameters."""
    sort, order = clean_sort_param(request, date_field=date_field)

    if qs.model is not Webapp and sort != date_field:
        # For when `Webapp` isn't the base model of the queryset.
        sort = 'addon__' + sort

    if order == 'asc':
        order_by = sort
    else:
        order_by = '-%s' % sort

    if sort == 'name':
        return order_by_translation(qs, order_by)
    elif sort == 'num_abuse_reports':
        return (qs.annotate(num_abuse_reports=Count('abuse_reports'))
                .order_by(order_by))
    else:
        return qs.order_by(order_by)


@permission_required('Apps', 'Review')
def queue_apps(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Version.uncached.filter(addon__type=amo.ADDON_WEBAPP,
                                  addon__disabled_by_user=False,
                                  addon__status=amo.STATUS_PENDING)
                          .exclude(addon__id__in=excluded_ids)
                          .order_by('nomination', 'created')
                          .select_related('addon').no_transforms())

    qs = _queue_to_apps(request, qs, date_field='nomination')
    apps = [QueuedApp(app, app.all_versions[0].nomination)
            for app in Webapp.version_and_file_transformer(qs)]

    return _queue(request, apps, 'pending')


@permission_required('Apps', 'Review')
def queue_rereview(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    rqs = (RereviewQueue.uncached
                        .filter(addon__type=amo.ADDON_WEBAPP,
                                addon__disabled_by_user=False)
                        .exclude(addon__in=excluded_ids))
    apps = _queue_to_apps(request, rqs)
    apps = [QueuedApp(app, app.rereviewqueue_set.all()[0].created)
            for app in apps]
    return _queue(request, apps, 'rereview')


@permission_required('Apps', 'ReviewEscalated')
def queue_escalated(request):
    eqs = EscalationQueue.uncached.filter(addon__type=amo.ADDON_WEBAPP,
                                          addon__disabled_by_user=False)
    apps = _queue_to_apps(request, eqs)
    apps = [QueuedApp(app, app.escalationqueue_set.all()[0].created)
            for app in apps]
    return _queue(request, apps, 'escalated')


@permission_required('Apps', 'Review')
def queue_updates(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    addon_ids = (File.objects.filter(status=amo.STATUS_PENDING,
                                     version__addon__is_packaged=True,
                                     version__addon__status=amo.STATUS_PUBLIC,
                                     version__addon__type=amo.ADDON_WEBAPP,
                                     version__addon__disabled_by_user=False,
                                     version__deleted=False)
                             .values_list('version__addon_id', flat=True))

    qs = _do_sort(
        request,
        Webapp.uncached.exclude(id__in=excluded_ids).filter(id__in=addon_ids))

    apps = [QueuedApp(app, app.all_versions[0].nomination)
            for app in Webapp.version_and_file_transformer(qs)]
    apps = sorted(apps, key=lambda a: a.created)
    return _queue(request, apps, 'updates')


@permission_required('Apps', 'Review')
def queue_moderated(request):
    """Queue for reviewing app reviews."""
    rf = (Review.uncached.exclude(Q(addon__isnull=True) |
                                  Q(reviewflag__isnull=True))
                .filter(addon__type=amo.ADDON_WEBAPP,
                        editorreview=True)
                .order_by('reviewflag__created'))

    page = paginate(request, rf, per_page=20)
    flags = dict(ReviewFlag.FLAGS)
    reviews_formset = ReviewFlagFormSet(request.POST or None,
                                        queryset=page.object_list,
                                        request=request)

    if reviews_formset.is_valid():
        reviews_formset.save()
        return redirect(reverse('reviewers.apps.queue_moderated'))

    return jingo.render(request, 'reviewers/queue.html',
                        context(reviews_formset=reviews_formset,
                                tab='moderated', page=page, flags=flags))


def _queue_to_apps(request, queue_qs, date_field='created'):
    """Apply sorting and filtering to queue queryset and return apps within
    that queue in sorted order.

    Args:
    queue_qs -- queue queryset (e.g. RereviewQueue, EscalationQueue)
    date_field -- field to sort on

    """
    # Preserve the sort order by storing the properly sorted ids.
    sorted_app_ids = (_do_sort(request, queue_qs, date_field=date_field)
                      .values_list('addon', flat=True))

    # The filter below undoes the sort above.
    qs = Webapp.objects.filter(id__in=sorted_app_ids)

    # Put the filtered qs back into the correct sort order.
    qs = manual_order(qs, sorted_app_ids, 'addons.id')

    return qs


def _get_search_form(request):
    form = ApiSearchForm()
    fields = [f.name for f in form.visible_fields() + form.hidden_fields()]
    get = dict((k, v) for k, v in request.GET.items() if k in fields)
    return ApiSearchForm(get or None)


@permission_required('Apps', 'Review')
def logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewAppLogForm(data)

    approvals = ActivityLog.objects.review_queue(webapp=True)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            approvals = approvals.filter(created__gte=data['start'])
        if data.get('end'):
            approvals = approvals.filter(created__lt=data['end'])
        if data.get('search'):
            term = data['search']
            approvals = approvals.filter(
                Q(commentlog__comments__icontains=term) |
                Q(applog__addon__name__localized_string__icontains=term) |
                Q(applog__addon__app_slug__icontains=term) |
                Q(user__display_name__icontains=term) |
                Q(user__username__icontains=term)).distinct()

    pager = paginate(request, approvals, 50)
    data = context(form=form, pager=pager, ACTION_DICT=amo.LOG_BY_ID,
                   tab='apps')
    return jingo.render(request, 'reviewers/logs.html', data)


@reviewer_required
def motd(request):
    form = None
    motd = unmemoized_get_config('mkt_reviewers_motd')
    if acl.action_allowed(request, 'AppReviewerMOTD', 'Edit'):
        form = MOTDForm(request.POST or None, initial={'motd': motd})
    if form and request.method == 'POST' and form.is_valid():
        set_config(u'mkt_reviewers_motd', form.cleaned_data['motd'])
        return redirect(reverse('reviewers.apps.motd'))
    data = context(form=form)
    return jingo.render(request, 'reviewers/motd.html', data)


# TODO: Move these to the validator when they live there someday.
PRIVILEGED_PERMISSIONS = set([
    'tcp-socket', 'contacts', 'device-storage:pictures',
    'device-storage:videos', 'device-storage:music', 'device-storage:sdcard',
    'browser', 'systemXHR', 'audio-channel-notification',
    'audio-channel-alarm'])
CERTIFIED_PERMISSIONS = set([
    'camera', 'tcp-socket', 'network-events', 'contacts',
    'device-storage:apps', 'device-storage:pictures',
    'device-storage:videos', 'device-storage:music', 'device-storage:sdcard',
    'sms', 'telephony', 'browser', 'bluetooth', 'mobileconnection', 'power',
    'settings', 'permissions', 'attention', 'webapps-manage',
    'backgroundservice', 'networkstats-manage', 'wifi-manage', 'systemXHR',
    'voicemail', 'deprecated-hwvideo', 'idle', 'time', 'embed-apps',
    'background-sensors', 'cellbroadcast', 'audio-channel-notification',
    'audio-channel-alarm', 'audio-channel-telephony', 'audio-channel-ringer',
    'audio-channel-publicnotification', 'open-remote-window'])


def _get_permissions(manifest):
    if 'permissions' not in manifest:
        return {}

    permissions = {}
    for perm in manifest['permissions'].keys():
        pval = permissions[perm] = {'type': 'web'}
        if perm in PRIVILEGED_PERMISSIONS:
            pval['type'] = 'priv'
        elif perm in CERTIFIED_PERMISSIONS:
            pval['type'] = 'cert'

        pval['description'] = manifest['permissions'][perm].get('description')

    return permissions


@permission_required('Apps', 'Review')
@addon_view
@json_view
def app_view_manifest(request, addon):
    manifest = {}
    success = False
    headers = ''
    if addon.is_packaged:
        version = addon.versions.latest()
        manifest = json.loads(_mini_manifest(addon, version.id))
        content = json.dumps(manifest, indent=4)
        success = True

    else:  # Show the hosted manifest_url.
        content, headers = u'', {}
        if addon.manifest_url:
            try:
                req = requests.get(addon.manifest_url, verify=False)
                content, headers = req.content, req.headers
                success = True
            except Exception:
                content = u''.join(traceback.format_exception(*sys.exc_info()))
            else:
                success = True

            try:
                # Reindent the JSON.
                manifest = json.loads(content)
                content = json.dumps(manifest, indent=4)
            except:
                # If it's not valid JSON, just return the content as is.
                pass

    return escape_all({'content': smart_decode(content),
                       'headers': headers,
                       'success': success,
                       'permissions': _get_permissions(manifest)})


@permission_required('Apps', 'Review')
def mini_manifest(request, addon_id, version_id):
    addon = get_object_or_404(Webapp, pk=addon_id)
    return http.HttpResponse(
        _mini_manifest(addon, version_id),
        content_type='application/x-web-app-manifest+json; charset=utf-8')


def _mini_manifest(addon, version_id):
    if not addon.is_packaged:
        raise http.Http404

    version = get_object_or_404(addon.versions, pk=version_id)
    file_ = version.all_files[0]
    manifest = addon.get_manifest_json(file_)

    data = {
        'name': manifest['name'],
        'version': version.version,
        'size': file_.size,
        'release_notes': version.releasenotes,
        'package_path': absolutify(
            reverse('reviewers.signed', args=[addon.app_slug, version.id]))
    }
    for key in ['developer', 'icons', 'locales']:
        if key in manifest:
            data[key] = manifest[key]

    return json.dumps(data, cls=JSONEncoder)


@permission_required('Apps', 'Review')
@addon_view
def app_abuse(request, addon):
    reports = AbuseReport.objects.filter(addon=addon).order_by('-created')
    total = reports.count()
    reports = paginate(request, reports, count=total)
    return jingo.render(request, 'reviewers/abuse.html',
                        context(addon=addon, reports=reports, total=total))


@permission_required('Apps', 'Review')
@addon_view
def get_signed_packaged(request, addon, version_id):
    version = get_object_or_404(addon.versions, pk=version_id)
    file = version.all_files[0]
    path = addon.sign_if_packaged(version_id, reviewer=True)
    if not path:
        raise http.Http404
    log.info('Returning signed package addon: %s, version: %s, path: %s' %
             (addon.pk, version_id, path))
    return HttpResponseSendFile(request, path, content_type='application/zip',
                                etag=file.hash.split(':')[-1])


@permission_required('Apps', 'Review')
def performance(request, username=None):

    is_admin = acl.action_allowed(request, 'Admin', '%')

    if username:
        if username == request.amo_user.username:
            user = request.amo_user
        elif is_admin:
            user = get_object_or_404(UserProfile, username=username)
        else:
            raise http.Http404
    else:
        user = request.amo_user

    today = datetime.date.today()
    month_ago = today - datetime.timedelta(days=30)
    year_ago = today - datetime.timedelta(days=365)

    total = ReviewerScore.get_total(user)
    totals = ReviewerScore.get_breakdown(user)
    months = ReviewerScore.get_breakdown_since(user, month_ago)
    years = ReviewerScore.get_breakdown_since(user, year_ago)

    def _sum(iter, types):
        return sum(s.total for s in iter if s.atype in types)

    breakdown = {
        'month': {
            'addons': _sum(months, amo.GROUP_TYPE_ADDON),
            'apps': _sum(months, amo.GROUP_TYPE_WEBAPP),
            'themes': _sum(months, amo.GROUP_TYPE_THEME),
        },
        'year': {
            'addons': _sum(years, amo.GROUP_TYPE_ADDON),
            'apps': _sum(years, amo.GROUP_TYPE_WEBAPP),
            'themes': _sum(years, amo.GROUP_TYPE_THEME),
        },
        'total': {
            'addons': _sum(totals, amo.GROUP_TYPE_ADDON),
            'apps': _sum(totals, amo.GROUP_TYPE_WEBAPP),
            'themes': _sum(totals, amo.GROUP_TYPE_THEME),
        }
    }

    ctx = context(**{
        'profile': user,
        'total': total,
        'breakdown': breakdown,
    })

    return jingo.render(request, 'reviewers/performance.html', ctx)


@permission_required('Apps', 'Review')
def leaderboard(request):

    return jingo.render(request, 'reviewers/leaderboard.html', context(**{
        'scores': ReviewerScore.all_users_by_score(),
    }))


@permission_required('Apps', 'Review')
@json_view
def apps_reviewing(request):

    return jingo.render(request, 'reviewers/apps_reviewing.html', context(**{
        'apps': AppsReviewing(request).get_apps(),
        'tab': 'reviewing'}))


@permission_required('Apps', 'Review')
def attachment(request, attachment):
    """
    Serve an attachment directly to the user.
    """
    try:
        a = ActivityLogAttachment.objects.get(pk=attachment)
        full_path = os.path.join(settings.REVIEWER_ATTACHMENTS_PATH,
                                 a.filepath)
        fsock = open(full_path, 'r')
    except (ActivityLogAttachment.DoesNotExist, IOError,):
        response = http.HttpResponseNotFound()
    else:
        filename = urllib.quote(a.filename())
        response = http.HttpResponse(fsock,
                                     mimetype='application/force-download')
        response['Content-Disposition'] = 'attachment; filename=%s' % filename
        response['Content-Length'] = os.path.getsize(full_path)
    return response
