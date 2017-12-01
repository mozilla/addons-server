from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
import json
import time

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.utils.translation import ugettext

from olympia import amo
from olympia.devhub import tasks as devhub_tasks
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.activity.models import ActivityLog, AddonLog, CommentLog
from olympia.addons.decorators import addon_view, addon_view_factory
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags, Persona)
from olympia.amo.decorators import (
    json_view, login_required, permission_required, post_required)
from olympia.amo.utils import paginate, render
from olympia.amo.urlresolvers import reverse
from olympia.constants.reviewers import REVIEWS_PER_PAGE, REVIEWS_PER_PAGE_MAX
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers import forms
from olympia.reviewers.models import (
    AddonCannedResponse, AutoApprovalSummary, clear_reviewing_cache,
    get_flags, get_reviewing_cache, get_reviewing_cache_key,
    PerformanceGraph, RereviewQueueTheme, ReviewerScore, ReviewerSubscription,
    set_reviewing_cache, ViewFullReviewQueue, ViewPendingQueue,
    ViewUnlistedAllList)
from olympia.reviewers.utils import (
    AutoApprovedTable, ContentReviewTable, is_limited_reviewer, ReviewHelper,
    ViewFullReviewQueueTable, ViewPendingQueueTable, ViewUnlistedAllListTable)
from olympia.users.models import UserProfile
from olympia.versions.models import Version
from olympia.zadmin.models import get_config, set_config

from .decorators import (
    addons_reviewer_required, any_reviewer_required,
    any_reviewer_or_moderator_required, ratings_moderator_required,
    unlisted_addons_reviewer_required)


def base_context(**kw):
    ctx = {'motd': get_config('reviewers_review_motd')}
    ctx.update(kw)
    return ctx


def context(request, **kw):
    admin_reviewer = is_admin_reviewer(request)
    limited_reviewer = is_limited_reviewer(request)
    ctx = {
        'queue_counts': queue_counts(admin_reviewer=admin_reviewer,
                                     limited_reviewer=limited_reviewer),
    }
    ctx.update(base_context(**kw))
    return ctx


@ratings_moderator_required
def eventlog(request):
    form = forms.EventLogForm(request.GET)
    eventlog = ActivityLog.objects.reviewer_events()
    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)

    if form.is_valid():
        if form.cleaned_data['start']:
            eventlog = eventlog.filter(created__gte=form.cleaned_data['start'])
        if form.cleaned_data['end']:
            eventlog = eventlog.filter(created__lt=form.cleaned_data['end'])
        if form.cleaned_data['filter']:
            eventlog = eventlog.filter(action=form.cleaned_data['filter'].id)

    pager = amo.utils.paginate(request, eventlog, 50)

    data = context(request, form=form, pager=pager,
                   motd_editable=motd_editable)

    return render(request, 'reviewers/eventlog.html', data)


@ratings_moderator_required
def eventlog_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.reviewer_events(), pk=id)

    review = None
    # I really cannot express the depth of the insanity incarnate in
    # our logging code...
    if len(log.arguments) > 1 and isinstance(log.arguments[1], Rating):
        review = log.arguments[1]

    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW)

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
        return redirect('reviewers.eventlog.detail', id)

    data = context(request, log=log, can_undelete=can_undelete)
    return render(request, 'reviewers/eventlog_detail.html', data)


@addons_reviewer_required
def beta_signed_log(request):
    """Log of all the beta files that got signed."""
    form = forms.BetaSignedLogForm(request.GET)
    beta_signed_log = ActivityLog.objects.beta_signed_events()
    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)

    if form.is_valid():
        if form.cleaned_data['filter']:
            beta_signed_log = beta_signed_log.filter(
                action=form.cleaned_data['filter'])

    pager = amo.utils.paginate(request, beta_signed_log, 50)

    data = context(request, form=form, pager=pager,
                   motd_editable=motd_editable)
    return render(request, 'reviewers/beta_signed_log.html', data)


@any_reviewer_or_moderator_required
def dashboard(request):
    # The dashboard is divided into sections that depend on what the reviewer
    # has access to, each section having one or more links, each link being
    # defined by a text and an URL. The template will show every link of every
    # section we provide in the context.
    sections = OrderedDict()
    view_all = acl.action_allowed(request, amo.permissions.REVIEWER_TOOLS_VIEW)
    admin_reviewer = is_admin_reviewer(request)
    if view_all or acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
        full_review_queue = ViewFullReviewQueue.objects
        pending_queue = ViewPendingQueue.objects
        if not admin_reviewer:
            full_review_queue = filter_admin_review_for_legacy_queue(
                full_review_queue)
            pending_queue = filter_admin_review_for_legacy_queue(
                pending_queue)

        sections[ugettext('Legacy Add-ons')] = [(
            ugettext('New Add-ons ({0})').format(
                full_review_queue.count()),
            reverse('reviewers.queue_nominated')
        ), (
            ugettext('Add-on Updates ({0})').format(
                pending_queue.count()),
            reverse('reviewers.queue_pending')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        ), (
            ugettext('Add-on Review Log'),
            reverse('reviewers.reviewlog')
        ), (
            ugettext('Signed Beta Files Log'),
            reverse('reviewers.beta_signed_log')
        ), (
            ugettext('Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide'
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDONS_POST_REVIEW):
        sections[ugettext('Auto-Approved Add-ons')] = [(
            ugettext('Auto Approved Add-ons ({0})').format(
                AutoApprovalSummary.get_auto_approved_queue(
                    admin_reviewer=admin_reviewer).count()),
            reverse('reviewers.queue_auto_approved')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        ), (
            ugettext('Add-on Review Log'),
            reverse('reviewers.reviewlog')
        ), (
            ugettext('Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide'
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDONS_CONTENT_REVIEW):
        sections[ugettext('Content Review')] = [(
            ugettext('Content Review ({0})').format(
                AutoApprovalSummary.get_content_review_queue(
                    admin_reviewer=admin_reviewer).count()),
            reverse('reviewers.queue_content_review')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.THEMES_REVIEW):
        sections[ugettext('Lightweight Themes')] = [(
            ugettext('New Themes ({0})').format(
                Persona.objects.filter(
                    addon__status=amo.STATUS_PENDING).count()),
            reverse('reviewers.themes.list')
        ), (
            ugettext('Themes Updates ({0})').format(
                RereviewQueueTheme.objects.count()),
            reverse('reviewers.themes.list_rereview')
        ), (
            ugettext('Flagged Themes ({0})').format(
                Persona.objects.filter(
                    addon__status=amo.STATUS_REVIEW_PENDING).count()),
            reverse('reviewers.themes.list_flagged')
        ), (
            ugettext('Themes Review Log'),
            reverse('reviewers.themes.logs')
        ), (
            ugettext('Deleted Themes Log'),
            reverse('reviewers.themes.deleted')
        ), (
            ugettext('Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines'
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.RATINGS_MODERATE):
        sections[ugettext('User Ratings Moderation')] = [(
            ugettext('Ratings Awaiting Moderation ({0})').format(
                Rating.objects.all().to_moderate().count()),
            reverse('reviewers.queue_moderated')
        ), (
            ugettext('Moderated Review Log'),
            reverse('reviewers.eventlog')
        ), (
            ugettext('Moderation Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation'
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDONS_REVIEW_UNLISTED):
        sections[ugettext('Unlisted Add-ons')] = [(
            ugettext('All Unlisted Add-ons'),
            reverse('reviewers.unlisted_queue_all')
        ), (
            ugettext('Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide'
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT):
        sections[ugettext('Announcement')] = [(
            ugettext('Update message of the day'),
            reverse('reviewers.motd')
        )]
    return render(request, 'reviewers/dashboard.html', base_context(**{
        # base_context includes motd.
        'sections': sections
    }))


@any_reviewer_required
def performance(request, user_id=False):
    user = request.user
    reviewers = _recent_reviewers()

    is_admin = (acl.action_allowed(request, amo.permissions.ADMIN) or
                acl.action_allowed(request,
                                   amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW))

    if is_admin and user_id:
        try:
            user = UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            pass  # Use request.user from above.

    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)

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

    def _sum(iter, types, exclude=False):
        """Sum the `total` property for items in `iter` that have an `atype`
        that is included in `types` when `exclude` is False (default) or not in
        `types` when `exclude` is True."""
        return sum(s.total
                   for s in iter
                   if (s.atype in types) == (not exclude))

    breakdown = {
        'month': {
            'addons': _sum(months, amo.GROUP_TYPE_ADDON),
            'themes': _sum(months, amo.GROUP_TYPE_THEME),
            'other': _sum(months, amo.GROUP_TYPE_ADDON + amo.GROUP_TYPE_THEME,
                          exclude=True)
        },
        'year': {
            'addons': _sum(years, amo.GROUP_TYPE_ADDON),
            'themes': _sum(years, amo.GROUP_TYPE_THEME),
            'other': _sum(years, amo.GROUP_TYPE_ADDON + amo.GROUP_TYPE_THEME,
                          exclude=True)
        },
        'total': {
            'addons': _sum(totals, amo.GROUP_TYPE_ADDON),
            'themes': _sum(totals, amo.GROUP_TYPE_THEME),
            'other': _sum(totals, amo.GROUP_TYPE_ADDON + amo.GROUP_TYPE_THEME,
                          exclude=True)
        }
    }

    data = context(request,
                   monthly_data=json.dumps(monthly_data),
                   performance_month=performance_total['month'],
                   performance_year=performance_total['year'],
                   breakdown=breakdown, point_total=point_total,
                   reviewers=reviewers, current_user=user, is_admin=is_admin,
                   is_user=(request.user.id == user.id),
                   motd_editable=motd_editable)

    return render(request, 'reviewers/performance.html', data)


def _recent_reviewers(days=90):
    since_date = datetime.now() - timedelta(days=days)
    reviewers = (
        UserProfile.objects.filter(
            activitylog__action__in=amo.LOG_REVIEWER_REVIEW_ACTION,
            activitylog__created__gt=since_date)
        .exclude(id=settings.TASK_USER_ID)
        .order_by('display_name')
        .distinct())
    return reviewers


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
    monthly_data = OrderedDict()

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
    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
    if motd_editable:
        form = forms.MOTDForm(
            initial={'motd': get_config('reviewers_review_motd')})
    data = context(request, form=form, motd_editable=motd_editable)
    return render(request, 'reviewers/motd.html', data)


@addons_reviewer_required
@post_required
def save_motd(request):
    if not acl.action_allowed(
            request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT):
        raise PermissionDenied
    form = forms.MOTDForm(request.POST)
    if form.is_valid():
        set_config('reviewers_review_motd', form.cleaned_data['motd'])
        return redirect(reverse('reviewers.motd'))
    data = context(request, form=form)
    return render(request, 'reviewers/motd.html', data)


def is_admin_reviewer(request):
    return acl.action_allowed(request,
                              amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW)


def filter_admin_review_for_legacy_queue(qs):
    return qs.filter(
        Q(needs_admin_code_review=None) | Q(needs_admin_code_review=False))


def _queue(request, TableObj, tab, qs=None, unlisted=False,
           SearchForm=forms.QueueSearchForm):
    if qs is None:
        qs = TableObj.Meta.model.objects.all()

    if SearchForm:
        if request.GET:
            search_form = SearchForm(request.GET)
            if search_form.is_valid():
                qs = search_form.filter_qs(qs)
        else:
            search_form = SearchForm()
        is_searching = search_form.data.get('searching')
    else:
        search_form = None
        is_searching = False
    admin_reviewer = is_admin_reviewer(request)

    # Those restrictions will only work with our RawSQLModel, so we need to
    # make sure we're not dealing with a regular Django ORM queryset first.
    if hasattr(qs, 'sql_model'):
        if not is_searching and not admin_reviewer:
            qs = filter_admin_review_for_legacy_queue(qs)
        if not unlisted:
            if is_limited_reviewer(request):
                qs = qs.having(
                    'waiting_time_hours >=', amo.REVIEW_LIMITED_DELAY_HOURS)

            # Hide webextensions from the listed queues so that human reviewers
            # don't pick them up: auto-approve cron should take care of them.
            qs = qs.filter(**{'files.is_webextension': False})

    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
    order_by = request.GET.get('sort', TableObj.default_order_by())
    if hasattr(TableObj, 'translate_sort_cols'):
        order_by = TableObj.translate_sort_cols(order_by)
    table = TableObj(data=qs, order_by=order_by)
    per_page = request.GET.get('per_page', REVIEWS_PER_PAGE)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = REVIEWS_PER_PAGE
    if per_page <= 0 or per_page > REVIEWS_PER_PAGE_MAX:
        per_page = REVIEWS_PER_PAGE
    page = paginate(request, table.rows, per_page=per_page)
    table.set_page(page)
    return render(request, 'reviewers/queue.html',
                  context(request, table=table, page=page, tab=tab,
                          search_form=search_form,
                          point_types=amo.REVIEWED_AMO,
                          unlisted=unlisted,
                          motd_editable=motd_editable))


def queue_counts(type=None, unlisted=False, admin_reviewer=False,
                 limited_reviewer=False, **kw):
    def construct_query_from_sql_model(sqlmodel, days_min=None, days_max=None):
        qs = sqlmodel.objects

        if not admin_reviewer:
            qs = filter_admin_review_for_legacy_queue(qs)
        if days_min:
            qs = qs.having('waiting_time_days >=', days_min)
        if days_max:
            qs = qs.having('waiting_time_days <=', days_max)
        if limited_reviewer:
            qs = qs.having('waiting_time_hours >=',
                           amo.REVIEW_LIMITED_DELAY_HOURS)
        return qs.count

    counts = {
        'pending': construct_query_from_sql_model(ViewPendingQueue, **kw),
        'nominated': construct_query_from_sql_model(ViewFullReviewQueue, **kw),
        'moderated': Rating.objects.all().to_moderate().count,
        'auto_approved': (
            AutoApprovalSummary.get_auto_approved_queue(
                admin_reviewer=admin_reviewer).count),
        'content_review': (
            AutoApprovalSummary.get_content_review_queue(
                admin_reviewer=admin_reviewer).count),
    }
    if unlisted:
        counts = {
            'all': construct_query_from_sql_model(ViewUnlistedAllList)
        }
    rv = {}
    if isinstance(type, basestring):
        return counts[type]()
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v()
    return rv


@addons_reviewer_required
def queue(request):
    return redirect(reverse('reviewers.queue_pending'))


@addons_reviewer_required
def queue_nominated(request):
    return _queue(request, ViewFullReviewQueueTable, 'nominated')


@addons_reviewer_required
def queue_pending(request):
    return _queue(request, ViewPendingQueueTable, 'pending')


@ratings_moderator_required
def queue_moderated(request):
    qs = Rating.objects.all().to_moderate().order_by('ratingflag__created')
    page = paginate(request, qs, per_page=20)
    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)

    flags = dict(RatingFlag.FLAGS)

    reviews_formset = forms.RatingFlagFormSet(request.POST or None,
                                              queryset=page.object_list,
                                              request=request)

    if request.method == 'POST':
        if reviews_formset.is_valid():
            reviews_formset.save()
        else:
            amo.messages.error(
                request,
                ' '.join(
                    e.as_text() or ugettext('An unknown error occurred')
                    for e in reviews_formset.errors))
        return redirect(reverse('reviewers.queue_moderated'))

    return render(request, 'reviewers/queue.html',
                  context(request, reviews_formset=reviews_formset,
                          tab='moderated', page=page, flags=flags,
                          search_form=None,
                          point_types=amo.REVIEWED_AMO,
                          motd_editable=motd_editable))


@unlisted_addons_reviewer_required
def unlisted_queue(request):
    return redirect(reverse('reviewers.unlisted_queue_all'))


@addons_reviewer_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application_id']
    f = forms.QueueSearchForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@permission_required(amo.permissions.ADDONS_CONTENT_REVIEW)
def queue_content_review(request):
    admin_reviewer = is_admin_reviewer(request)
    qs = (
        AutoApprovalSummary.get_content_review_queue(
            admin_reviewer=admin_reviewer)
        .select_related('addonapprovalscounter')
        .order_by('addonapprovalscounter__last_content_review', 'created')
    )
    return _queue(request, ContentReviewTable, 'content_review',
                  qs=qs, SearchForm=None)


@permission_required(amo.permissions.ADDONS_POST_REVIEW)
def queue_auto_approved(request):
    admin_reviewer = is_admin_reviewer(request)
    qs = (
        AutoApprovalSummary.get_auto_approved_queue(
            admin_reviewer=admin_reviewer)
        .select_related(
            'addonapprovalscounter', '_current_version__autoapprovalsummary')
        .order_by(
            '-_current_version__autoapprovalsummary__weight',
            'addonapprovalscounter__last_human_review',
            'created'))
    return _queue(request, AutoApprovedTable, 'auto_approved',
                  qs=qs, SearchForm=None)


def _get_comments_for_hard_deleted_versions(addon):
    """Versions are soft-deleted now but we need to grab review history for
    older deleted versions that were hard-deleted so the only record we have
    of them is in the review log.  Hard deletion was pre Feb 2016.

    We don't know if they were unlisted or listed but given the time overlap
    they're most likely listed so we assume that."""
    class PseudoVersion(object):
        def __init__(self):
            self.all_activity = []

        all_files = ()
        approvalnotes = None
        compatible_apps_ordered = ()
        releasenotes = None
        status = 'Deleted'
        deleted = True
        channel = amo.RELEASE_CHANNEL_LISTED
        is_ready_for_auto_approval = False

        @property
        def created(self):
            return self.all_activity[0].created

        @property
        def version(self):
            return (self.all_activity[0].activity_log
                        .details.get('version', '[deleted]'))

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
    return comment_versions.values()


def perform_review_permission_checks(
        request, addon, channel, content_review_only=False):
    """Perform the permission checks needed by the review() view or anything
    that follows the same behavior, such as the whiteboard() view.

    Raises PermissionDenied when the current user on the request does not have
    the right permissions for the context defined by addon, channel and
    content_review_only boolean.
    """
    unlisted_only = (
        channel == amo.RELEASE_CHANNEL_UNLISTED or
        not addon.has_listed_versions())
    was_auto_approved = (
        channel == amo.RELEASE_CHANNEL_LISTED and
        addon.current_version and addon.current_version.was_auto_approved)

    # Are we looking at an unlisted review page, or (weirdly) the listed
    # review page of an unlisted-only add-on?
    if unlisted_only and not acl.check_unlisted_addons_reviewer(request):
        raise PermissionDenied

    # If we're only doing a content review, we just need to check for the
    # content review permission, otherwise it's the "main" review page.
    if content_review_only:
        if not acl.action_allowed(
                request, amo.permissions.ADDONS_CONTENT_REVIEW):
            raise PermissionDenied
    else:
        # Was the add-on auto-approved?
        if was_auto_approved and not acl.action_allowed(
                request, amo.permissions.ADDONS_POST_REVIEW):
            raise PermissionDenied

        # Finally, if it wasn't auto-approved, check for legacy reviewer
        # permission.
        if not was_auto_approved and not acl.action_allowed(
                request, amo.permissions.ADDONS_REVIEW):
            raise PermissionDenied


def determine_channel(channel_as_text):
    """Determine which channel the review is for according to the channel
    parameter as text, and whether we should be in content-review only mode."""
    if channel_as_text == 'content':
        # 'content' is not a real channel, just a different review mode for
        # listed add-ons.
        content_review_only = True
        channel = 'listed'
    else:
        content_review_only = False
    # channel is passed in as text, but we want the constant.
    channel = amo.CHANNEL_CHOICES_LOOKUP.get(
        channel_as_text, amo.RELEASE_CHANNEL_LISTED)
    return channel, content_review_only


# Permission checks for this view are done inside, depending on type of review
# needed, using perform_review_permission_checks().
@login_required
@addon_view_factory(qs=Addon.unfiltered.all)
def review(request, addon, channel=None):
    whiteboard_url = reverse(
        'reviewers.whiteboard',
        args=(channel or 'listed', addon.slug if addon.slug else addon.pk))
    channel, content_review_only = determine_channel(channel)

    was_auto_approved = (
        channel == amo.RELEASE_CHANNEL_LISTED and
        addon.current_version and addon.current_version.was_auto_approved)

    # If we're just looking (GET) we can bypass the specific permissions checks
    # if we have ReviewerTools:View.
    bypass_more_specific_permissions_because_read_only = (
        request.method == 'GET' and acl.action_allowed(
            request, amo.permissions.REVIEWER_TOOLS_VIEW))

    if not bypass_more_specific_permissions_because_read_only:
        perform_review_permission_checks(
            request, addon, channel, content_review_only=content_review_only)

    # Find the last version (ignoring beta and disabled: they don't need to be
    # reviewed, betas are always public and disabled will revert to their
    # original status if they are ever re-enabled), it will be the version we
    # want to review.
    version = addon.find_latest_version(channel=channel)

    if not settings.ALLOW_SELF_REVIEWS and addon.has_author(request.user):
        amo.messages.warning(
            request, ugettext('Self-reviews are not allowed.'))
        return redirect(reverse('reviewers.queue'))

    # Get the current info request state to set as the default.
    form_initial = {'info_request': version and version.has_info_request}

    form_helper = ReviewHelper(
        request=request, addon=addon, version=version,
        content_review_only=content_review_only)
    form = forms.ReviewForm(request.POST if request.method == 'POST' else None,
                            helper=form_helper, initial=form_initial)
    is_admin = acl.action_allowed(request, amo.permissions.ADDONS_EDIT)

    approvals_info = None
    reports = None
    user_ratings = None
    if channel == amo.RELEASE_CHANNEL_LISTED:
        if was_auto_approved:
            try:
                approvals_info = addon.addonapprovalscounter
            except AddonApprovalsCounter.DoesNotExist:
                pass

        developers = addon.listed_authors
        reports = Paginator(
            (AbuseReport.objects
                        .filter(Q(addon=addon) | Q(user__in=developers))
                        .order_by('-created')), 5).page(1)
        user_ratings = Paginator(
            (Rating.without_replies
                   .filter(addon=addon, rating__lte=3, body__isnull=False)
                   .order_by('-created')), 5).page(1)

        if content_review_only:
            queue_type = 'content_review'
        elif was_auto_approved:
            queue_type = 'auto_approved'
        else:
            queue_type = form.helper.handler.review_type
        redirect_url = reverse('reviewers.queue_%s' % queue_type)
    else:
        redirect_url = reverse('reviewers.unlisted_queue_all')

    if request.method == 'POST' and form.is_valid():
        form.helper.process()
        if form.cleaned_data.get('notify'):
            ReviewerSubscription.objects.get_or_create(user=request.user,
                                                       addon=addon)
        if is_admin:
            flags_data = {}
            if form.cleaned_data.get('clear_admin_code_review'):
                flags_data['needs_admin_code_review'] = False
            if form.cleaned_data.get('clear_admin_content_review'):
                flags_data['needs_admin_content_review'] = False
            if flags_data:
                try:
                    reviewerflags = addon.addonreviewerflags
                    reviewerflags.update(**flags_data)
                except AddonReviewerFlags.DoesNotExist:
                    # If it does not exist, there is nothing to unflag.
                    pass
        amo.messages.success(
            request, ugettext('Review successfully processed.'))
        clear_reviewing_cache(addon.id)
        return redirect(redirect_url)

    # Kick off validation tasks for any files in this version which don't have
    # cached validation, since reviewers will almost certainly need to access
    # them. But only if we're not running in eager mode, since that could mean
    # blocking page load for several minutes.
    if version and not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
        for file_ in version.all_files:
            if not file_.has_been_validated:
                devhub_tasks.validate(file_)

    canned = AddonCannedResponse.objects.all()
    actions = form.helper.actions.items()

    try:
        # Find the previously approved version to compare to.
        show_diff = version and (
            addon.versions.exclude(id=version.id).filter(
                # We're looking for a version that was either manually approved
                # or auto-approved but then confirmed.
                Q(autoapprovalsummary__isnull=True) |
                Q(autoapprovalsummary__verdict=amo.AUTO_APPROVED,
                  autoapprovalsummary__confirmed=True)
            ).filter(
                channel=channel,
                files__isnull=False,
                created__lt=version.created,
                files__status=amo.STATUS_PUBLIC).latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we should show a minimal form for.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    # The actions we should show the comments form for (contrary to minimal
    # form above, it defaults to True, because most actions do need to have
    # the comments form).
    actions_comments = [k for (k, a) in actions if a.get('comments', True)]

    # The actions we should show the 'info request' checkbox for.
    actions_info_request = [k for (k, a) in actions
                            if a.get('info_request', False)]

    versions = (Version.unfiltered.filter(addon=addon, channel=channel)
                                  .select_related('autoapprovalsummary')
                                  .exclude(files__status=amo.STATUS_BETA)
                                  .order_by('-created')
                                  .transform(Version.transformer_activity)
                                  .transform(Version.transformer))

    # We assume comments on old deleted versions are for listed versions.
    # See _get_comments_for_hard_deleted_versions above for more detail.
    all_versions = (_get_comments_for_hard_deleted_versions(addon)
                    if channel == amo.RELEASE_CHANNEL_LISTED else [])
    all_versions.extend(versions)
    all_versions.sort(key=lambda v: v.created,
                      reverse=True)

    pager = amo.utils.paginate(request, all_versions, 10)
    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    auto_approval_info = {}
    # Now that we've paginated the versions queryset, iterate on them to
    # generate auto approvals info. Note that the variable should not clash
    # the already existing 'version'.
    for a_version in pager.object_list:
        if not a_version.is_ready_for_auto_approval:
            continue
        try:
            summary = a_version.autoapprovalsummary
        except AutoApprovalSummary.DoesNotExist:
            auto_approval_info[a_version.pk] = None
            continue
        # Call calculate_verdict() again, it will use the data already stored.
        verdict_info = summary.calculate_verdict(pretty=True)
        auto_approval_info[a_version.pk] = verdict_info

    if version:
        flags = get_flags(version)
    else:
        flags = []

    user_changes_actions = [
        amo.LOG.ADD_USER_WITH_ROLE.id,
        amo.LOG.CHANGE_USER_WITH_ROLE.id,
        amo.LOG.REMOVE_USER_WITH_ROLE.id]
    user_changes_log = AddonLog.objects.filter(
        activity_log__action__in=user_changes_actions,
        addon=addon).order_by('id')
    ctx = context(
        request, actions=actions, actions_comments=actions_comments,
        actions_info_request=actions_info_request,
        actions_minimal=actions_minimal, addon=addon,
        approvals_info=approvals_info, auto_approval_info=auto_approval_info,
        canned=canned, content_review_only=content_review_only, count=count,
        flags=flags, form=form, is_admin=is_admin, num_pages=num_pages,
        pager=pager, reports=reports, show_diff=show_diff,
        unlisted=(channel == amo.RELEASE_CHANNEL_UNLISTED),
        user_changes=user_changes_log, user_ratings=user_ratings,
        version=version, was_auto_approved=was_auto_approved,
        whiteboard_form=forms.WhiteboardForm(instance=addon),
        whiteboard_url=whiteboard_url)
    return render(request, 'reviewers/review.html', ctx)


@never_cache
@json_view
@any_reviewer_required
def review_viewing(request):
    if 'addon_id' not in request.POST:
        return {}

    addon_id = request.POST['addon_id']
    user_id = request.user.id
    current_name = ''
    is_user = 0
    key = get_reviewing_cache_key(addon_id)
    user_key = '%s:review_viewing_user:%s' % (settings.CACHE_PREFIX, user_id)
    interval = amo.REVIEWER_VIEWING_INTERVAL

    # Check who is viewing.
    currently_viewing = get_reviewing_cache(addon_id)

    # If nobody is viewing or current user is, set current user as viewing
    if not currently_viewing or currently_viewing == user_id:
        # Get a list of all the reviews this user is locked on.
        review_locks = cache.get_many(cache.get(user_key, {}))
        can_lock_more_reviews = (
            len(review_locks) < amo.REVIEWER_REVIEW_LOCK_LIMIT or
            acl.action_allowed(request,
                               amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW))
        if can_lock_more_reviews or currently_viewing == user_id:
            set_reviewing_cache(addon_id, user_id)
            # Give it double expiry just to be safe.
            cache.set(user_key, set(review_locks) | {key}, interval * 4)
            currently_viewing = user_id
            current_name = request.user.name
            is_user = 1
        else:
            currently_viewing = settings.TASK_USER_ID
            current_name = ugettext('Review lock limit reached')
            is_user = 2
    else:
        current_name = UserProfile.objects.get(pk=currently_viewing).name

    return {'current': currently_viewing, 'current_name': current_name,
            'is_user': is_user, 'interval_seconds': interval}


@never_cache
@json_view
@any_reviewer_required
def queue_viewing(request):
    if 'addon_ids' not in request.POST:
        return {}

    viewing = {}
    user_id = request.user.id

    for addon_id in request.POST['addon_ids'].split(','):
        addon_id = addon_id.strip()
        key = get_reviewing_cache_key(addon_id)
        currently_viewing = cache.get(key)
        if currently_viewing and currently_viewing != user_id:
            viewing[addon_id] = (UserProfile.objects
                                            .get(id=currently_viewing)
                                            .display_name)

    return viewing


@json_view
@any_reviewer_required
def queue_version_notes(request, addon_id):
    addon = get_object_or_404(Addon.objects, pk=addon_id)
    version = addon.latest_version
    return {'releasenotes': unicode(version.releasenotes),
            'approvalnotes': version.approvalnotes}


@json_view
@any_reviewer_required
def queue_review_text(request, log_id):
    review = get_object_or_404(CommentLog, activity_log_id=log_id)
    return {'reviewtext': review.comments}


@any_reviewer_required
def reviewlog(request):
    data = request.GET.copy()

    motd_editable = acl.action_allowed(
        request, amo.permissions.ADDON_REVIEWER_MOTD_EDIT)

    if not data.get('start') and not data.get('end'):
        today = date.today()
        data['start'] = date(today.year, today.month, 1)

    form = forms.ReviewLogForm(data)

    approvals = ActivityLog.objects.review_log()
    if not acl.check_unlisted_addons_reviewer(request):
        # Only display logs related to unlisted versions to users with the
        # right permission.
        list_channel = amo.RELEASE_CHANNEL_LISTED
        approvals = approvals.filter(versionlog__version__channel=list_channel)

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
    data = context(request, form=form, pager=pager,
                   motd_editable=motd_editable)
    return render(request, 'reviewers/reviewlog.html', data)


@any_reviewer_required
@addon_view
def abuse_reports(request, addon):
    developers = addon.listed_authors
    reports = AbuseReport.objects.filter(
        Q(addon=addon) | Q(user__in=developers)).order_by('-created')
    reports = amo.utils.paginate(request, reports)
    data = context(request, addon=addon, reports=reports)
    return render(request, 'reviewers/abuse_reports.html', data)


@any_reviewer_required
def leaderboard(request):
    return render(request, 'reviewers/leaderboard.html', context(
        request, scores=ReviewerScore.all_users_by_score()))


# Permission checks for this view are done inside, depending on type of review
# needed, using perform_review_permission_checks().
@login_required
@addon_view_factory(qs=Addon.unfiltered.all)
def whiteboard(request, addon, channel):
    channel_as_text = channel
    channel, content_review_only = determine_channel(channel)
    perform_review_permission_checks(
        request, addon, channel, content_review_only=content_review_only)

    form = forms.WhiteboardForm(request.POST or None, instance=addon)

    if form.is_valid():
        addon = form.save()
        return redirect('reviewers.review', channel_as_text,
                        addon.slug if addon.slug else addon.pk)
    raise PermissionDenied


@unlisted_addons_reviewer_required
def unlisted_list(request):
    return _queue(request, ViewUnlistedAllListTable, 'all',
                  unlisted=True, SearchForm=forms.AllAddonSearchForm)
