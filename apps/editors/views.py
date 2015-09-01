from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import time

from django import http
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.datastructures import SortedDict
from django.views.decorators.cache import never_cache

from tower import ugettext as _

import amo
import devhub.tasks
from abuse.models import AbuseReport
from access import acl
from addons.decorators import addon_view, addon_view_factory
from addons.models import Addon, Version
from amo.decorators import json_view, post_required
from amo.utils import paginate
from amo.urlresolvers import reverse
from devhub.models import ActivityLog, AddonLog, CommentLog
from editors import forms
from editors.models import (AddonCannedResponse, EditorSubscription, EventLog,
                            PerformanceGraph, ReviewerScore,
                            ViewFastTrackQueue, ViewFullReviewQueue,
                            ViewPendingQueue, ViewPreliminaryQueue,
                            ViewQueue,
                            ViewUnlistedFullReviewQueue,
                            ViewUnlistedPendingQueue,
                            ViewUnlistedPreliminaryQueue)
from editors.helpers import (ViewFastTrackQueueTable, ViewFullReviewQueueTable,
                             ViewPendingQueueTable, ViewPreliminaryQueueTable,
                             ViewUnlistedFullReviewQueueTable,
                             ViewUnlistedPendingQueueTable,
                             ViewUnlistedPreliminaryQueueTable)
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from zadmin.models import get_config, set_config

from .decorators import (addons_reviewer_required, any_reviewer_required,
                         unlisted_addons_reviewer_required)


def base_context(**kw):
    ctx = dict(motd=get_config('editors_review_motd'))
    ctx.update(kw)
    return ctx


def context(request, **kw):
    admin_reviewer = is_admin_reviewer(request)
    ctx = dict(admin_reviewer=admin_reviewer,
               queue_counts=queue_counts(admin_reviewer=admin_reviewer),
               unlisted_queue_counts=queue_counts(
                   unlisted=True, admin_reviewer=admin_reviewer))
    ctx.update(base_context(**kw))
    return ctx


@addons_reviewer_required
def eventlog(request):
    form = forms.EventLogForm(request.GET)
    eventlog = ActivityLog.objects.editor_events()

    if form.is_valid():
        if form.cleaned_data['start']:
            eventlog = eventlog.filter(created__gte=form.cleaned_data['start'])
        if form.cleaned_data['end']:
            eventlog = eventlog.filter(created__lt=form.cleaned_data['end'])
        if form.cleaned_data['filter']:
            eventlog = eventlog.filter(action=form.cleaned_data['filter'].id)

    pager = amo.utils.paginate(request, eventlog, 50)

    data = context(request, form=form, pager=pager)
    return render(request, 'editors/eventlog.html', data)


@addons_reviewer_required
def eventlog_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.editor_events(), pk=id)

    review = None
    # I really cannot express the depth of the insanity incarnate in
    # our logging code...
    if len(log.arguments) > 1 and isinstance(log.arguments[1], Review):
        review = log.arguments[1]

    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

    can_undelete = review and review.deleted and (
        is_admin or request.user.pk == log.user.pk)

    if request.method == 'POST':
        # A Form seems overkill for this.
        if request.POST['action'] == 'undelete':
            if not can_undelete:
                raise PermissionDenied

            ReviewerScore.award_moderation_points(
                log.user, review.addon, review.id, undo=True)
            review.undelete()
        return redirect('editors.eventlog.detail', id)

    data = context(request, log=log, can_undelete=can_undelete)
    return render(request, 'editors/eventlog_detail.html', data)


@addons_reviewer_required
def beta_signed_log(request):
    """Log of all the beta files that got signed."""
    form = forms.BetaSignedLogForm(request.GET)
    beta_signed_log = ActivityLog.objects.beta_signed_events()

    if form.is_valid():
        if form.cleaned_data['filter']:
            beta_signed_log = beta_signed_log.filter(
                action=form.cleaned_data['filter'])

    pager = amo.utils.paginate(request, beta_signed_log, 50)

    data = context(request, form=form, pager=pager)
    return render(request, 'editors/beta_signed_log.html', data)


@any_reviewer_required
def home(request):
    if (not acl.action_allowed(request, 'Addons', 'Review') and
            acl.action_allowed(request, 'Personas', 'Review')):
        return http.HttpResponseRedirect(reverse('editors.themes.home'))

    durations = (('new', _('New Add-ons (Under 5 days)')),
                 ('med', _('Passable (5 to 10 days)')),
                 ('old', _('Overdue (Over 10 days)')))

    progress, percentage = _editor_progress()
    unlisted_progress, unlisted_percentage = _editor_progress(unlisted=True)
    reviews_max_display = getattr(settings, 'EDITOR_REVIEWS_MAX_DISPLAY', 5)
    reviews_total = ActivityLog.objects.total_reviews()[:reviews_max_display]
    reviews_monthly = (
        ActivityLog.objects.monthly_reviews()[:reviews_max_display])
    reviews_total_count = ActivityLog.objects.user_approve_reviews(
        request.user).count()
    reviews_monthly_count = (
        ActivityLog.objects.current_month_user_approve_reviews(
            request.user).count())

    # Try to read user position from retrieved reviews.
    # If not available, query for it.
    reviews_total_position = (
        ActivityLog.objects.user_position(reviews_total, request.user)
        or ActivityLog.objects.total_reviews_user_position(request.user))

    reviews_monthly_position = (
        ActivityLog.objects.user_position(reviews_monthly, request.user)
        or ActivityLog.objects.monthly_reviews_user_position(request.user))

    data = context(
        request,
        reviews_total=reviews_total,
        reviews_monthly=reviews_monthly,
        reviews_total_count=reviews_total_count,
        reviews_monthly_count=reviews_monthly_count,
        reviews_total_position=reviews_total_position,
        reviews_monthly_position=reviews_monthly_position,
        new_editors=EventLog.new_editors(),
        eventlog=ActivityLog.objects.editor_events()[:6],
        progress=progress,
        unlisted_progress=unlisted_progress,
        percentage=percentage,
        unlisted_percentage=unlisted_percentage,
        durations=durations,
        reviews_max_display=reviews_max_display)

    return render(request, 'editors/home.html', data)


def _editor_progress(unlisted=False):
    """Return the progress (number of add-ons still unreviewed for a given
       period of time) and the percentage (out of all add-ons of that type)."""

    types = ['nominated', 'prelim', 'pending']
    progress = {'new': queue_counts(types, days_max=4, unlisted=unlisted),
                'med': queue_counts(types, days_min=5, days_max=10,
                                    unlisted=unlisted),
                'old': queue_counts(types, days_min=11, unlisted=unlisted)}

    # Return the percent of (p)rogress out of (t)otal.
    def pct(p, t):
        return (p / float(t)) * 100 if p > 0 else 0

    percentage = {}
    for t in types:
        total = progress['new'][t] + progress['med'][t] + progress['old'][t]
        percentage[t] = {}
        for duration in ('new', 'med', 'old'):
            percentage[t][duration] = pct(progress[duration][t], total)

    return (progress, percentage)


@addons_reviewer_required
def performance(request, user_id=False):
    user = request.amo_user
    editors = _recent_editors()

    is_admin = (acl.action_allowed(request, 'Admin', '%') or
                acl.action_allowed(request, 'ReviewerAdminTools', 'View'))

    if is_admin and user_id:
        try:
            user = UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            pass  # Use request.amo_user from above.

    monthly_data = _performance_by_month(user.id)
    performance_total = _performance_total(monthly_data)

    # Incentive point breakdown.
    today = date.today()
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    point_total = ReviewerScore.get_total(user)
    totals = ReviewerScore.get_breakdown(user)
    months = ReviewerScore.get_breakdown_since(user, month_ago)
    years = ReviewerScore.get_breakdown_since(user, year_ago)

    def _sum(iter, types):
        return sum(s.total for s in iter if s.atype in types)

    breakdown = {
        'month': {
            'addons': _sum(months, amo.GROUP_TYPE_ADDON),
            'themes': _sum(months, amo.GROUP_TYPE_THEME),
        },
        'year': {
            'addons': _sum(years, amo.GROUP_TYPE_ADDON),
            'themes': _sum(years, amo.GROUP_TYPE_THEME),
        },
        'total': {
            'addons': _sum(totals, amo.GROUP_TYPE_ADDON),
            'themes': _sum(totals, amo.GROUP_TYPE_THEME),
        }
    }

    data = context(request,
                   monthly_data=json.dumps(monthly_data),
                   performance_month=performance_total['month'],
                   performance_year=performance_total['year'],
                   breakdown=breakdown, point_total=point_total,
                   editors=editors, current_user=user, is_admin=is_admin,
                   is_user=(request.amo_user.id == user.id))

    return render(request, 'editors/performance.html', data)


def _recent_editors(days=90):
    since_date = datetime.now() - timedelta(days=days)
    editors = (UserProfile.objects
                          .filter(activitylog__action__in=amo.LOG_REVIEW_QUEUE,
                                  activitylog__created__gt=since_date)
                          .order_by('display_name')
                          .distinct())
    return editors


def _performance_total(data):
    # TODO(gkoberger): Fix this so it's the past X, rather than this X to date.
    # (ex: March 15-April 15, not April 1 - April 15)
    total_yr = dict(usercount=0, teamamt=0, teamcount=0, teamavg=0)
    total_month = dict(usercount=0, teamamt=0, teamcount=0, teamavg=0)
    current_year = datetime.now().year

    for k, val in data.items():
        if k.startswith(str(current_year)):
            total_yr['usercount'] = total_yr['usercount'] + val['usercount']
            total_yr['teamamt'] = total_yr['teamamt'] + val['teamamt']
            total_yr['teamcount'] = total_yr['teamcount'] + val['teamcount']

    current_label_month = datetime.now().isoformat()[:7]
    if current_label_month in data:
        total_month = data[current_label_month]

    return dict(month=total_month, year=total_yr)


def _performance_by_month(user_id, months=12, end_month=None, end_year=None):
    monthly_data = SortedDict()

    now = datetime.now()
    if not end_month:
        end_month = now.month
    if not end_year:
        end_year = now.year

    end_time = time.mktime((end_year, end_month + 1, 1, 0, 0, 0, 0, 0, -1))
    start_time = time.mktime((end_year, end_month + 1 - months,
                              1, 0, 0, 0, 0, 0, -1))

    sql = (PerformanceGraph.objects
           .filter_raw('log_activity.created >=',
                       date.fromtimestamp(start_time).isoformat())
           .filter_raw('log_activity.created <',
                       date.fromtimestamp(end_time).isoformat()))

    for row in sql.all():
        label = row.approval_created.isoformat()[:7]

        if label not in monthly_data:
            xaxis = row.approval_created.strftime('%b %Y')
            monthly_data[label] = dict(teamcount=0, usercount=0,
                                       teamamt=0, label=xaxis)

        monthly_data[label]['teamamt'] = monthly_data[label]['teamamt'] + 1
        monthly_data_count = monthly_data[label]['teamcount']
        monthly_data[label]['teamcount'] = monthly_data_count + row.total

        if row.user_id == user_id:
            user_count = monthly_data[label]['usercount']
            monthly_data[label]['usercount'] = user_count + row.total

    # Calculate averages
    for i, vals in monthly_data.items():
        average = round(vals['teamcount'] / float(vals['teamamt']), 1)
        monthly_data[i]['teamavg'] = str(average)  # floats aren't valid json

    return monthly_data


@addons_reviewer_required
def motd(request):
    form = None
    if acl.action_allowed(request, 'AddonReviewerMOTD', 'Edit'):
        form = forms.MOTDForm(
            initial={'motd': get_config('editors_review_motd')})
    data = context(request, form=form)
    return render(request, 'editors/motd.html', data)


@addons_reviewer_required
@post_required
def save_motd(request):
    if not acl.action_allowed(request, 'AddonReviewerMOTD', 'Edit'):
        raise PermissionDenied
    form = forms.MOTDForm(request.POST)
    if form.is_valid():
        set_config('editors_review_motd', form.cleaned_data['motd'])
        return redirect(reverse('editors.motd'))
    data = context(request, form=form)
    return render(request, 'editors/motd.html', data)


def is_admin_reviewer(request):
    return acl.action_allowed(request, 'ReviewerAdminTools', 'View')


def filter_admin_only_addons(queryset):
    return queryset.filter(admin_review=False, has_info_request=False)


def _queue(request, TableObj, tab, qs=None, unlisted=False):
    if qs is None:
        qs = TableObj.Meta.model.objects.all()
    admin_reviewer = is_admin_reviewer(request)
    if not admin_reviewer:
        qs = filter_admin_only_addons(qs)
    if request.GET:
        search_form = forms.QueueSearchForm(request.GET)
        if search_form.is_valid():
            qs = search_form.filter_qs(qs)
    else:
        search_form = forms.QueueSearchForm()
    order_by = request.GET.get('sort', TableObj.default_order_by())
    order_by = TableObj.translate_sort_cols(order_by)
    table = TableObj(data=qs, order_by=order_by)
    default = 100
    per_page = request.GET.get('per_page', default)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = default
    if per_page <= 0 or per_page > 200:
        per_page = default
    page = paginate(request, table.rows, per_page=per_page)
    table.set_page(page)
    return render(request, 'editors/queue.html',
                  context(request, table=table, page=page, tab=tab,
                          search_form=search_form,
                          point_types=amo.REVIEWED_AMO,
                          unlisted=unlisted))


def queue_counts(type=None, unlisted=False, admin_reviewer=None, **kw):
    def construct_query(query_type, days_min=None, days_max=None):
        def apply_query(query, *args):
            query = query.having(*args)
            return query

        query = query_type.objects
        # admin_reviewer defaults to True so explicitly check against False.
        if admin_reviewer is False:
            query = filter_admin_only_addons(query)

        if days_min:
            query = apply_query(query, 'waiting_time_days >=', days_min)
        if days_max:
            query = apply_query(query, 'waiting_time_days <=', days_max)

        return query.count

    counts = {'pending': construct_query(ViewPendingQueue, **kw),
              'nominated': construct_query(ViewFullReviewQueue, **kw),
              'prelim': construct_query(ViewPreliminaryQueue, **kw),
              'fast_track': construct_query(ViewFastTrackQueue, **kw),
              'moderated': (
                  Review.objects.filter(reviewflag__isnull=False,
                                        editorreview=1).count)}
    if unlisted:
        counts = {
            'pending': construct_query(ViewUnlistedPendingQueue, **kw),
            'nominated': construct_query(ViewUnlistedFullReviewQueue, **kw),
            'prelim': construct_query(ViewUnlistedPreliminaryQueue, **kw)}
    rv = {}
    if isinstance(type, basestring):
        return counts[type]()
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v()
    return rv


@addons_reviewer_required
def queue(request):
    return redirect(reverse('editors.queue_pending'))


@addons_reviewer_required
def queue_nominated(request):
    return _queue(request, ViewFullReviewQueueTable, 'nominated')


@addons_reviewer_required
def queue_pending(request):
    return _queue(request, ViewPendingQueueTable, 'pending')


@addons_reviewer_required
def queue_prelim(request):
    return _queue(request, ViewPreliminaryQueueTable, 'prelim')


@addons_reviewer_required
def queue_fast_track(request):
    return _queue(request, ViewFastTrackQueueTable, 'fast_track')


@addons_reviewer_required
def queue_moderated(request):
    rf = (Review.objects.exclude(Q(addon__isnull=True) |
                                 Q(reviewflag__isnull=True))
                        .filter(editorreview=1)
                        .order_by('reviewflag__created'))

    page = paginate(request, rf, per_page=20)

    flags = dict(ReviewFlag.FLAGS)

    reviews_formset = ReviewFlagFormSet(request.POST or None,
                                        queryset=page.object_list,
                                        request=request)

    if request.method == 'POST':
        if reviews_formset.is_valid():
            reviews_formset.save()
        else:
            amo.messages.error(
                request, ' '.join(e.as_text() or _('An unknown error occurred')
                                  for e in reviews_formset.errors))
        return redirect(reverse('editors.queue_moderated'))

    return render(request, 'editors/queue.html',
                  context(request, reviews_formset=reviews_formset,
                          tab='moderated', page=page, flags=flags,
                          search_form=None,
                          point_types=amo.REVIEWED_AMO))


@unlisted_addons_reviewer_required
def unlisted_queue(request):
    return redirect(reverse('editors.unlisted_queue_pending'))


@unlisted_addons_reviewer_required
def unlisted_queue_nominated(request):
    return _queue(request, ViewUnlistedFullReviewQueueTable, 'nominated',
                  unlisted=True)


@unlisted_addons_reviewer_required
def unlisted_queue_pending(request):
    return _queue(request, ViewUnlistedPendingQueueTable, 'pending',
                  unlisted=True)


@unlisted_addons_reviewer_required
def unlisted_queue_prelim(request):
    return _queue(request, ViewUnlistedPreliminaryQueueTable, 'prelim',
                  unlisted=True)


@addons_reviewer_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application_id']
    f = forms.QueueSearchForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@addons_reviewer_required
@addon_view_factory(qs=Addon.with_unlisted.all)
def review(request, addon):
    if not addon.is_listed and not acl.check_unlisted_addons_reviewer(request):
        raise http.Http404

    version = addon.latest_version

    if not settings.ALLOW_SELF_REVIEWS and addon.has_author(request.amo_user):
        amo.messages.warning(request, _('Self-reviews are not allowed.'))
        return redirect(reverse('editors.queue'))

    form = forms.get_review_form(request.POST or None, request=request,
                                 addon=addon, version=version)

    queue_type = (form.helper.review_type if form.helper.review_type
                  != 'preliminary' else 'prelim')
    if addon.is_listed:
        redirect_url = reverse('editors.queue_%s' % queue_type)
    else:
        redirect_url = reverse('editors.unlisted_queue_%s' % queue_type)

    is_admin = acl.action_allowed(request, 'Addons', 'Edit')

    if request.method == 'POST' and form.is_valid():
        form.helper.process()
        if form.cleaned_data.get('notify'):
            EditorSubscription.objects.get_or_create(user=request.amo_user,
                                                     addon=addon)
        if form.cleaned_data.get('adminflag') and is_admin:
            addon.update(admin_review=False)
        amo.messages.success(request, _('Review successfully processed.'))
        return redirect(redirect_url)

    # Kick off validation tasks for any files in this version which don't have
    # cached validation, since editors will almost certainly need to access
    # them. But only if we're not running in eager mode, since that could mean
    # blocking page load for several minutes.
    if not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
        for file_ in version.files.all():
            if not file_.has_been_validated:
                devhub.tasks.validate(file_)

    canned = AddonCannedResponse.objects.all()
    actions = form.helper.actions.items()

    statuses = [amo.STATUS_PUBLIC, amo.STATUS_LITE,
                amo.STATUS_LITE_AND_NOMINATED]

    try:
        show_diff = (addon.versions.exclude(id=version.id)
                                   .filter(files__isnull=False,
                                           created__lt=version.created,
                                           files__status__in=statuses)
                                   .latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we should show a minimal form from.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    versions = (Version.objects.filter(addon=addon)
                               .exclude(files__status=amo.STATUS_BETA)
                               .order_by('-created')
                               .transform(Version.transformer_activity)
                               .transform(Version.transformer))

    class PseudoVersion(object):
        def __init__(self):
            self.all_activity = []

        all_files = ()
        approvalnotes = None
        compatible_apps_ordered = ()
        releasenotes = None
        status = 'Deleted',

        @property
        def created(self):
            return self.all_activity[0].created

        @property
        def version(self):
            return (self.all_activity[0].activity_log
                        .details.get('version', '[deleted]'))

    # Grab review history for deleted versions of this add-on
    comments = (CommentLog.objects
                .filter(activity_log__action__in=amo.LOG_REVIEW_QUEUE,
                        activity_log__versionlog=None,
                        activity_log__addonlog__addon=addon)
                .order_by('created')
                .select_related('activity_log'))

    comment_versions = defaultdict(PseudoVersion)
    for c in comments:
        c.version = c.activity_log.details.get('version', c.created)
        comment_versions[c.version].all_activity.append(c)

    all_versions = comment_versions.values()
    all_versions.extend(versions)
    all_versions.sort(key=lambda v: v.created,
                      reverse=True)

    pager = amo.utils.paginate(request, all_versions, 10)

    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    try:
        flags = ViewQueue.objects.get(id=addon.id).flags
    except ViewQueue.DoesNotExist:
        flags = []

    user_changes_actions = [
        amo.LOG.ADD_USER_WITH_ROLE.id,
        amo.LOG.CHANGE_USER_WITH_ROLE.id,
        amo.LOG.REMOVE_USER_WITH_ROLE.id]
    user_changes_log = AddonLog.objects.filter(
        activity_log__action__in=user_changes_actions,
        addon=addon).order_by('id')
    ctx = context(request, version=version, addon=addon,
                  pager=pager, num_pages=num_pages, count=count, flags=flags,
                  form=form, canned=canned, is_admin=is_admin,
                  show_diff=show_diff,
                  actions=actions, actions_minimal=actions_minimal,
                  whiteboard_form=forms.WhiteboardForm(instance=addon),
                  user_changes=user_changes_log,
                  unlisted=not addon.is_listed)

    return render(request, 'editors/review.html', ctx)


@never_cache
@json_view
@addons_reviewer_required
def review_viewing(request):
    if 'addon_id' not in request.POST:
        return {}

    addon_id = request.POST['addon_id']
    user_id = request.amo_user.id
    current_name = ''
    is_user = 0
    key = '%s:review_viewing:%s' % (settings.CACHE_PREFIX, addon_id)
    interval = amo.EDITOR_VIEWING_INTERVAL

    # Check who is viewing.
    currently_viewing = cache.get(key)

    # If nobody is viewing or current user is, set current user as viewing
    if not currently_viewing or currently_viewing == user_id:
        # We want to save it for twice as long as the ping interval,
        # just to account for latency and the like.
        cache.set(key, user_id, interval * 2)
        currently_viewing = user_id
        current_name = request.amo_user.name
        is_user = 1
    else:
        current_name = UserProfile.objects.get(pk=currently_viewing).name

    return {'current': currently_viewing, 'current_name': current_name,
            'is_user': is_user, 'interval_seconds': interval}


@never_cache
@json_view
@addons_reviewer_required
def queue_viewing(request):
    if 'addon_ids' not in request.POST:
        return {}

    viewing = {}
    user_id = request.amo_user.id

    for addon_id in request.POST['addon_ids'].split(','):
        addon_id = addon_id.strip()
        key = '%s:review_viewing:%s' % (settings.CACHE_PREFIX, addon_id)
        currently_viewing = cache.get(key)
        if currently_viewing and currently_viewing != user_id:
            viewing[addon_id] = (UserProfile.objects
                                            .get(id=currently_viewing)
                                            .display_name)

    return viewing


@json_view
@addons_reviewer_required
def queue_version_notes(request, addon_id):
    addon = get_object_or_404(Addon, pk=addon_id)
    version = addon.latest_version
    return {'releasenotes': unicode(version.releasenotes),
            'approvalnotes': version.approvalnotes}


@addons_reviewer_required
def reviewlog(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = date.today()
        data['start'] = date(today.year, today.month, 1)

    form = forms.ReviewLogForm(data)

    approvals = ActivityLog.objects.review_queue()
    if not acl.check_unlisted_addons_reviewer(request):
        # Display logs related to unlisted add-ons only to senior reviewers.
        approvals = approvals.filter(addonlog__addon__is_listed=True)

    if form.is_valid():
        data = form.cleaned_data
        if data['start']:
            approvals = approvals.filter(created__gte=data['start'])
        if data['end']:
            approvals = approvals.filter(created__lt=data['end'])
        if data['search']:
            term = data['search']
            approvals = approvals.filter(
                Q(commentlog__comments__icontains=term) |
                Q(addonlog__addon__name__localized_string__icontains=term) |
                Q(user__display_name__icontains=term) |
                Q(user__username__icontains=term)).distinct()

    pager = amo.utils.paginate(request, approvals, 50)
    ad = {
        amo.LOG.APPROVE_VERSION.id: _('was approved'),
        amo.LOG.PRELIMINARY_VERSION.id: _('given preliminary review'),
        amo.LOG.REJECT_VERSION.id: _('rejected'),
        amo.LOG.ESCALATE_VERSION.id: _(
            'escalated', 'editors_review_history_nominated_adminreview'),
        amo.LOG.REQUEST_INFORMATION.id: _('needs more information'),
        amo.LOG.REQUEST_SUPER_REVIEW.id: _('needs super review'),
        amo.LOG.COMMENT_VERSION.id: _('commented'),
    }
    data = context(request, form=form, pager=pager, ACTION_DICT=ad)
    return render(request, 'editors/reviewlog.html', data)


@addons_reviewer_required
@addon_view
def abuse_reports(request, addon):
    reports = AbuseReport.objects.filter(addon=addon).order_by('-created')
    total = reports.count()
    reports = amo.utils.paginate(request, reports)
    data = context(request, addon=addon, reports=reports, total=total)
    return render(request, 'editors/abuse_reports.html', data)


@addons_reviewer_required
def leaderboard(request):
    return render(request, 'editors/leaderboard.html', context(
        request, scores=ReviewerScore.all_users_by_score()))


@addons_reviewer_required
@addon_view_factory(qs=Addon.with_unlisted.all)
def whiteboard(request, addon):
    form = forms.WhiteboardForm(request.POST or None, instance=addon)

    if form.is_valid():
        addon = form.save()
        return redirect('editors.review', addon.pk)
    raise PermissionDenied
