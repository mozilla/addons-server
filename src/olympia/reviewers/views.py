import functools
import json
import time

from collections import OrderedDict
from datetime import date, datetime, timedelta

from django import http
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import urlquote
from django.utils.translation import ugettext
from django.views.decorators.cache import never_cache

import pygit2

from csp.decorators import csp as set_csp
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.mixins import (
    CreateModelMixin, DestroyModelMixin, ListModelMixin, RetrieveModelMixin,
    UpdateModelMixin)
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.accounts.views import API_TOKEN_COOKIE
from olympia.activity.models import ActivityLog, CommentLog, DraftComment
from olympia.addons.decorators import addon_view, owner_or_unlisted_reviewer
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags, ReusedGUID)
from olympia.amo.decorators import (
    json_view, login_required, permission_required, post_required)
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import paginate, render
from olympia.api.permissions import (
    AllowAddonAuthor, AllowAnyKindOfReviewer, AllowReviewer,
    AllowReviewerUnlisted, AnyOf, GroupPermission)
from olympia.constants.reviewers import REVIEWS_PER_PAGE, REVIEWS_PER_PAGE_MAX
from olympia.devhub import tasks as devhub_tasks
from olympia.discovery.models import DiscoveryItem
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.forms import (
    AllAddonSearchForm, MOTDForm, PublicWhiteboardForm, QueueSearchForm,
    RatingFlagFormSet, RatingModerationLogForm, ReviewForm, ReviewLogForm,
    WhiteboardForm)
from olympia.reviewers.models import (
    AutoApprovalSummary, CannedResponse, PerformanceGraph, ReviewerScore,
    ReviewerSubscription, ViewExtensionQueue, ViewRecommendedQueue,
    ViewThemeFullReviewQueue, ViewThemePendingQueue, Whiteboard,
    clear_reviewing_cache, get_flags, get_reviewing_cache,
    get_reviewing_cache_key, set_reviewing_cache)
from olympia.reviewers.serializers import (
    AddonBrowseVersionSerializer, AddonCompareVersionSerializer,
    AddonReviewerFlagsSerializer, CannedResponseSerializer,
    DiffableVersionSerializer, DraftCommentSerializer, FileEntriesSerializer)
from olympia.reviewers.utils import (
    AutoApprovedTable, ContentReviewTable, ExpiredInfoRequestsTable,
    NeedsHumanReviewTable, ReviewHelper, ViewUnlistedAllListTable,
    view_table_factory)
from olympia.users.models import UserProfile
from olympia.versions.models import Version
from olympia.zadmin.models import get_config, set_config

from .decorators import (
    any_reviewer_or_moderator_required, any_reviewer_required,
    permission_or_tools_view_required, unlisted_addons_reviewer_required)


def reviewer_addon_view_factory(f):
    decorator = functools.partial(
        addon_view, qs=Addon.unfiltered.all,
        include_deleted_when_checking_versions=True)
    return decorator(f)


def context(**kw):
    ctx = {'motd': get_config('reviewers_review_motd')}
    ctx.update(kw)
    return ctx


@permission_or_tools_view_required(amo.permissions.RATINGS_MODERATE)
def ratings_moderation_log(request):
    form = RatingModerationLogForm(request.GET)
    mod_log = ActivityLog.objects.moderation_events()

    if form.is_valid():
        if form.cleaned_data['start']:
            mod_log = mod_log.filter(created__gte=form.cleaned_data['start'])
        if form.cleaned_data['end']:
            mod_log = mod_log.filter(created__lt=form.cleaned_data['end'])
        if form.cleaned_data['filter']:
            mod_log = mod_log.filter(action=form.cleaned_data['filter'].id)

    pager = paginate(request, mod_log, 50)

    data = context(form=form, pager=pager)

    return render(request, 'reviewers/moderationlog.html', data)


@permission_or_tools_view_required(amo.permissions.RATINGS_MODERATE)
def ratings_moderation_log_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.moderation_events(), pk=id)

    review = None
    # I really cannot express the depth of the insanity incarnate in
    # our logging code...
    if len(log.arguments) > 1 and isinstance(log.arguments[1], Rating):
        review = log.arguments[1]

    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)

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
        return redirect('reviewers.ratings_moderation_log.detail', id)

    data = context(log=log, can_undelete=can_undelete)
    return render(request, 'reviewers/moderationlog_detail.html', data)


@any_reviewer_or_moderator_required
def dashboard(request):
    # The dashboard is divided into sections that depend on what the reviewer
    # has access to, each section having one or more links, each link being
    # defined by a text and an URL. The template will show every link of every
    # section we provide in the context.
    sections = OrderedDict()
    view_all = acl.action_allowed(request, amo.permissions.REVIEWER_TOOLS_VIEW)
    admin_reviewer = is_admin_reviewer(request)
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDONS_REVIEW):
        review_queue = ViewExtensionQueue.objects
        if not admin_reviewer:
            review_queue = filter_admin_review_for_legacy_queue(
                review_queue)

        sections[ugettext('Pre-Review Add-ons')] = []
        if acl.action_allowed(
                request, amo.permissions.ADDONS_RECOMMENDED_REVIEW):
            recommended_queue_count = ViewRecommendedQueue.objects.count()
            sections[ugettext('Pre-Review Add-ons')].append((
                ugettext('Recommended ({0})').format(recommended_queue_count),
                reverse('reviewers.queue_recommended')
            ))
        sections[ugettext('Pre-Review Add-ons')].extend(((
            ugettext('Other Pending Review ({0})').format(
                review_queue.count()),
            reverse('reviewers.queue_extension')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        ), (
            ugettext('Review Log'),
            reverse('reviewers.reviewlog')
        ), (
            ugettext('Add-on Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide'
        ),
        ))
        sections[ugettext('Flagged By Scanners')] = [(
            ugettext('Flagged By Scanners ({0})').format(
                Addon.objects.get_needs_human_review_queue(
                    admin_reviewer=admin_reviewer).count()),
            reverse('reviewers.queue_needs_human_review'))
        ]
    if view_all or acl.action_allowed(
            request, amo.permissions.ADDONS_POST_REVIEW):
        sections[ugettext('Auto-Approved Add-ons')] = [(
            ugettext('Auto Approved Add-ons ({0})').format(
                Addon.objects.get_auto_approved_queue(
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
                Addon.objects.get_content_review_queue(
                    admin_reviewer=admin_reviewer).count()),
            reverse('reviewers.queue_content_review')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        )]
    if view_all or acl.action_allowed(
            request, amo.permissions.STATIC_THEMES_REVIEW):
        full_review_queue = ViewThemeFullReviewQueue.objects
        pending_queue = ViewThemePendingQueue.objects
        if not admin_reviewer:
            full_review_queue = filter_admin_review_for_legacy_queue(
                full_review_queue)
            pending_queue = filter_admin_review_for_legacy_queue(
                pending_queue)

        sections[ugettext('Themes')] = [(
            ugettext('New ({0})').format(full_review_queue.count()),
            reverse('reviewers.queue_theme_nominated')
        ), (
            ugettext('Updates ({0})').format(pending_queue.count()),
            reverse('reviewers.queue_theme_pending')
        ), (
            ugettext('Performance'),
            reverse('reviewers.performance')
        ), (
            ugettext('Review Log'),
            reverse('reviewers.reviewlog')
        ), (
            ugettext('Theme Review Guide'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines'
        ),
        ]
    if view_all or acl.action_allowed(
            request, amo.permissions.RATINGS_MODERATE):
        sections[ugettext('User Ratings Moderation')] = [(
            ugettext('Ratings Awaiting Moderation ({0})').format(
                Rating.objects.all().to_moderate().count()),
            reverse('reviewers.queue_moderated')
        ), (
            ugettext('Moderated Review Log'),
            reverse('reviewers.ratings_moderation_log')
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
    if view_all or acl.action_allowed(
            request, amo.permissions.REVIEWS_ADMIN):
        expired = (
            Addon.objects.filter(
                addonreviewerflags__pending_info_request__lt=datetime.now(),
                status__in=(amo.STATUS_NOMINATED, amo.STATUS_APPROVED),
                disabled_by_user=False)
            .order_by('addonreviewerflags__pending_info_request'))

        sections[ugettext('Admin Tools')] = [(
            ugettext('Expired Information Requests ({0})'.format(
                expired.count())),
            reverse('reviewers.queue_expired_info_requests')
        )]
    return render(request, 'reviewers/dashboard.html', context(**{
        # base_context includes motd.
        'sections': sections
    }))


@any_reviewer_required
def performance(request, user_id=False):
    user = request.user
    reviewers = _recent_reviewers()

    is_admin = acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN)

    if is_admin and user_id:
        try:
            user = UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            pass  # Use request.user from above.

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

    data = context(monthly_data=json.dumps(monthly_data),
                   performance_month=performance_total['month'],
                   performance_year=performance_total['year'],
                   breakdown=breakdown, point_total=point_total,
                   reviewers=reviewers, current_user=user, is_admin=is_admin,
                   is_user=(request.user.id == user.id))

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


@permission_required(amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
def motd(request):
    form = None
    form = MOTDForm(initial={'motd': get_config('reviewers_review_motd')})
    data = context(form=form)
    return render(request, 'reviewers/motd.html', data)


@permission_required(amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
@post_required
def save_motd(request):
    form = MOTDForm(request.POST)
    if form.is_valid():
        set_config('reviewers_review_motd', form.cleaned_data['motd'])
        return redirect(reverse('reviewers.motd'))
    data = context(form=form)
    return render(request, 'reviewers/motd.html', data)


def is_admin_reviewer(request):
    return acl.action_allowed(request,
                              amo.permissions.REVIEWS_ADMIN)


def filter_admin_review_for_legacy_queue(qs):
    return qs.filter(
        Q(needs_admin_code_review=None) | Q(needs_admin_code_review=False),
        Q(needs_admin_theme_review=None) | Q(needs_admin_theme_review=False))


def _queue(request, TableObj, tab, qs=None, unlisted=False,
           SearchForm=QueueSearchForm):
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
    page = paginate(request, table.rows, per_page=per_page, count=qs.count())
    table.set_page(page)

    queue_counts = fetch_queue_counts(admin_reviewer=admin_reviewer)

    return render(request, 'reviewers/queue.html',
                  context(table=table, page=page, tab=tab,
                          search_form=search_form,
                          point_types=amo.REVIEWED_AMO,
                          unlisted=unlisted,
                          queue_counts=queue_counts))


def fetch_queue_counts(admin_reviewer):
    def construct_query_from_sql_model(sqlmodel):
        qs = sqlmodel.objects

        if not admin_reviewer:
            qs = filter_admin_review_for_legacy_queue(qs)
        return qs.count

    expired = (
        Addon.objects.filter(
            addonreviewerflags__pending_info_request__lt=datetime.now(),
            status__in=(amo.STATUS_NOMINATED, amo.STATUS_APPROVED),
            disabled_by_user=False)
        .order_by('addonreviewerflags__pending_info_request'))

    counts = {
        'extension': construct_query_from_sql_model(
            ViewExtensionQueue),
        'theme_pending': construct_query_from_sql_model(
            ViewThemePendingQueue),
        'theme_nominated': construct_query_from_sql_model(
            ViewThemeFullReviewQueue),
        'recommended': construct_query_from_sql_model(
            ViewRecommendedQueue),
        'moderated': Rating.objects.all().to_moderate().count,
        'auto_approved': (
            Addon.objects.get_auto_approved_queue(
                admin_reviewer=admin_reviewer).count),
        'content_review': (
            Addon.objects.get_content_review_queue(
                admin_reviewer=admin_reviewer).count),
        'needs_human_review': (
            Addon.objects.get_needs_human_review_queue(
                admin_reviewer=admin_reviewer).count),
        'expired_info_requests': expired.count,
    }
    return {queue: count() for (queue, count) in counts.items()}


@permission_or_tools_view_required(amo.permissions.ADDONS_REVIEW)
def queue_extension(request):
    return _queue(request, view_table_factory(ViewExtensionQueue), 'extension')


@permission_or_tools_view_required(amo.permissions.ADDONS_RECOMMENDED_REVIEW)
def queue_recommended(request):
    return _queue(
        request, view_table_factory(ViewRecommendedQueue),
        'recommended')


@permission_or_tools_view_required(amo.permissions.STATIC_THEMES_REVIEW)
def queue_theme_nominated(request):
    return _queue(
        request, view_table_factory(ViewThemeFullReviewQueue),
        'theme_nominated')


@permission_or_tools_view_required(amo.permissions.STATIC_THEMES_REVIEW)
def queue_theme_pending(request):
    return _queue(
        request, view_table_factory(ViewThemePendingQueue),
        'theme_pending')


@permission_or_tools_view_required(amo.permissions.RATINGS_MODERATE)
def queue_moderated(request):
    qs = Rating.objects.all().to_moderate().order_by('ratingflag__created')
    page = paginate(request, qs, per_page=20)

    flags = dict(RatingFlag.FLAGS)

    reviews_formset = RatingFlagFormSet(request.POST or None,
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

    admin_reviewer = is_admin_reviewer(request)
    queue_counts = fetch_queue_counts(admin_reviewer=admin_reviewer)

    return render(request, 'reviewers/queue.html',
                  context(reviews_formset=reviews_formset,
                          tab='moderated', page=page, flags=flags,
                          search_form=None,
                          point_types=amo.REVIEWED_AMO,
                          queue_counts=queue_counts))


@any_reviewer_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application_id']
    form = QueueSearchForm()
    return {'choices': form.version_choices_for_app_id(app_id)}


@permission_or_tools_view_required(amo.permissions.ADDONS_CONTENT_REVIEW)
def queue_content_review(request):
    admin_reviewer = is_admin_reviewer(request)
    qs = Addon.objects.get_content_review_queue(
        admin_reviewer=admin_reviewer
    )
    return _queue(request, ContentReviewTable, 'content_review',
                  qs=qs, SearchForm=None)


@permission_or_tools_view_required(amo.permissions.ADDONS_POST_REVIEW)
def queue_auto_approved(request):
    admin_reviewer = is_admin_reviewer(request)
    qs = Addon.objects.get_auto_approved_queue(
        admin_reviewer=admin_reviewer)
    return _queue(request, AutoApprovedTable, 'auto_approved',
                  qs=qs, SearchForm=None)


@permission_required(amo.permissions.REVIEWS_ADMIN)
def queue_expired_info_requests(request):
    qs = (
        Addon.objects.filter(
            addonreviewerflags__pending_info_request__lt=datetime.now(),
            status__in=(amo.STATUS_NOMINATED, amo.STATUS_APPROVED),
            disabled_by_user=False)
        .order_by('addonreviewerflags__pending_info_request'))
    return _queue(request, ExpiredInfoRequestsTable, 'expired_info_requests',
                  qs=qs, SearchForm=None)


@permission_or_tools_view_required(amo.permissions.ADDONS_REVIEW)
def queue_needs_human_review(request):
    admin_reviewer = is_admin_reviewer(request)
    qs = Addon.objects.get_needs_human_review_queue(
        admin_reviewer=admin_reviewer)
    return _queue(request, NeedsHumanReviewTable, 'needs_human_review',
                  qs=qs, SearchForm=None)


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
        not addon.has_listed_versions(include_deleted=True))
    was_auto_approved = (
        channel == amo.RELEASE_CHANNEL_LISTED and
        addon.current_version and addon.current_version.was_auto_approved)
    static_theme = addon.type == amo.ADDON_STATICTHEME
    try:
        is_recommendable = addon.discoveryitem.recommendable
    except DiscoveryItem.DoesNotExist:
        is_recommendable = False

    # Are we looking at an unlisted review page, or (weirdly) the listed
    # review page of an unlisted-only add-on?
    if unlisted_only and not acl.check_unlisted_addons_reviewer(request):
        raise PermissionDenied
    # Recommended add-ons need special treatment.
    if is_recommendable and not acl.action_allowed(
            request, amo.permissions.ADDONS_RECOMMENDED_REVIEW):
        raise PermissionDenied
    # If we're only doing a content review, we just need to check for the
    # content review permission, otherwise it's the "main" review page.
    if content_review_only:
        if not acl.action_allowed(
                request, amo.permissions.ADDONS_CONTENT_REVIEW):
            raise PermissionDenied
    elif static_theme:
        if not acl.action_allowed(
                request, amo.permissions.STATIC_THEMES_REVIEW):
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
@reviewer_addon_view_factory
def review(request, addon, channel=None):
    whiteboard_url = reverse(
        'reviewers.whiteboard',
        args=(channel or 'listed', addon.slug if addon.slug else addon.pk))
    channel, content_review_only = determine_channel(channel)

    was_auto_approved = (
        channel == amo.RELEASE_CHANNEL_LISTED and
        addon.current_version and addon.current_version.was_auto_approved)
    is_static_theme = addon.type == amo.ADDON_STATICTHEME
    try:
        is_recommendable = addon.discoveryitem.recommendable
    except DiscoveryItem.DoesNotExist:
        is_recommendable = False

    # If we're just looking (GET) we can bypass the specific permissions checks
    # if we have ReviewerTools:View.
    bypass_more_specific_permissions_because_read_only = (
        request.method == 'GET' and acl.action_allowed(
            request, amo.permissions.REVIEWER_TOOLS_VIEW))

    if not bypass_more_specific_permissions_because_read_only:
        perform_review_permission_checks(
            request, addon, channel, content_review_only=content_review_only)

    version = addon.find_latest_version(channel=channel, exclude=())

    if not settings.ALLOW_SELF_REVIEWS and addon.has_author(request.user):
        amo.messages.warning(
            request, ugettext('Self-reviews are not allowed.'))
        return redirect(reverse('reviewers.dashboard'))

    # Queryset to be paginated for versions. We use the default ordering to get
    # most recently created first (Note that the template displays each page
    # in reverse order, older first).
    versions_qs = (
        # We want to load all Versions, even deleted ones, while using the
        # addon.versions related manager to get `addon` property pre-cached on
        # each version.
        addon.versions(manager='unfiltered_for_relations')
             .filter(channel=channel)
             .select_related('autoapprovalsummary')
        # Add activity transformer to prefetch all related activity logs on
        # top of the regular transformers.
             .transform(Version.transformer_activity)
    )

    form_initial = {
        # Get the current info request state to set as the default.
        'info_request': addon.pending_info_request,
    }

    form_helper = ReviewHelper(
        request=request, addon=addon, version=version,
        content_review_only=content_review_only)
    form = ReviewForm(request.POST if request.method == 'POST' else None,
                      helper=form_helper, initial=form_initial)
    is_admin = acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN)

    approvals_info = None
    reports = Paginator(
        (AbuseReport.objects
            .filter(Q(addon=addon) | Q(user__in=addon.listed_authors))
            .select_related('user')
            .prefetch_related(
                # Should only need translations for addons on abuse reports,
                # so let's prefetch the add-on with them and avoid repeating
                # a ton of potentially duplicate queries with all the useless
                # Addon transforms.
                Prefetch(
                    'addon', queryset=Addon.objects.all().only_translations())
            )
            .order_by('-created')), 5).page(1)
    user_ratings = Paginator(
        (Rating.without_replies
            .filter(addon=addon, rating__lte=3, body__isnull=False)
            .order_by('-created')), 5).page(1)
    if channel == amo.RELEASE_CHANNEL_LISTED:
        if was_auto_approved:
            try:
                approvals_info = addon.addonapprovalscounter
            except AddonApprovalsCounter.DoesNotExist:
                pass

        if content_review_only:
            queue_type = 'content_review'
        elif is_recommendable:
            queue_type = 'recommended'
        elif was_auto_approved:
            queue_type = 'auto_approved'
        elif is_static_theme:
            queue_type = form.helper.handler.review_type
        else:
            queue_type = 'extension'
        redirect_url = reverse('reviewers.queue_%s' % queue_type)
    else:
        redirect_url = reverse('reviewers.unlisted_queue_all')

    if request.method == 'POST' and form.is_valid():
        form.helper.process()

        amo.messages.success(
            request, ugettext('Review successfully processed.'))
        clear_reviewing_cache(addon.id)
        return redirect(form.helper.redirect_url or redirect_url)

    # Kick off validation tasks for any files in this version which don't have
    # cached validation, since reviewers will almost certainly need to access
    # them. But only if we're not running in eager mode, since that could mean
    # blocking page load for several minutes.
    if version and not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        for file_ in version.all_files:
            if not file_.has_been_validated:
                devhub_tasks.validate(file_)

    actions = form.helper.actions.items()

    try:
        # Find the previously approved version to compare to.
        show_diff = version and (
            addon.versions.exclude(id=version.id).filter(
                # We're looking for a version that was either manually approved
                # (either it has no auto approval summary, or it has one but
                # with a negative verdict because it was locked by a reviewer
                # who then approved it themselves), or auto-approved but then
                # confirmed.
                Q(autoapprovalsummary__isnull=True) |
                Q(autoapprovalsummary__verdict=amo.NOT_AUTO_APPROVED) |
                Q(autoapprovalsummary__verdict=amo.AUTO_APPROVED,
                  autoapprovalsummary__confirmed=True)
            ).filter(
                channel=channel,
                files__isnull=False,
                created__lt=version.created,
                files__status=amo.STATUS_APPROVED).latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we shouldn't show a minimal form for.
    actions_full = [
        k for (k, a) in actions if not (is_static_theme or a.get('minimal'))]

    # The actions we should show the comments form for (contrary to minimal
    # form above, it defaults to True, because most actions do need to have
    # the comments form).
    actions_comments = [k for (k, a) in actions if a.get('comments', True)]

    deleted_addon_ids = (
        ReusedGUID.objects.filter(guid=addon.guid).values_list(
            'addon_id', flat=True) if addon.guid else [])

    pager = paginate(request, versions_qs, 10)
    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    auto_approval_info = {}
    version_ids = []
    # Now that we've paginated the versions queryset, iterate on them to
    # generate auto approvals info. Note that the variable should not clash
    # the already existing 'version'.
    for a_version in pager.object_list:
        version_ids.append(a_version.pk)
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

    # We want to notify the reviewer if there are versions needing extra
    # attention that are not present in the versions history (which is
    # paginated).
    versions_flagged_by_scanners = versions_qs.filter(
        needs_human_review=True).exclude(pk__in=version_ids).count()

    flags = get_flags(addon, version) if version else []

    try:
        whiteboard = Whiteboard.objects.get(pk=addon.pk)
    except Whiteboard.DoesNotExist:
        whiteboard = Whiteboard(pk=addon.pk)

    wb_form_cls = PublicWhiteboardForm if is_static_theme else WhiteboardForm
    whiteboard_form = wb_form_cls(instance=whiteboard, prefix='whiteboard')

    user_changes_actions = [
        amo.LOG.ADD_USER_WITH_ROLE.id,
        amo.LOG.CHANGE_USER_WITH_ROLE.id,
        amo.LOG.REMOVE_USER_WITH_ROLE.id]
    user_changes_log = ActivityLog.objects.filter(
        action__in=user_changes_actions, addonlog__addon=addon).order_by('id')
    ctx = context(
        actions=actions, actions_comments=actions_comments,
        actions_full=actions_full, addon=addon,
        api_token=request.COOKIES.get(API_TOKEN_COOKIE, None),
        approvals_info=approvals_info, auto_approval_info=auto_approval_info,
        content_review_only=content_review_only, count=count,
        deleted_addon_ids=deleted_addon_ids, flags=flags,
        form=form, is_admin=is_admin, now=datetime.now(), num_pages=num_pages,
        pager=pager, reports=reports, show_diff=show_diff,
        subscribed=ReviewerSubscription.objects.filter(
            user=request.user, addon=addon).exists(),
        unlisted=(channel == amo.RELEASE_CHANNEL_UNLISTED),
        user_changes_log=user_changes_log, user_ratings=user_ratings,
        versions_flagged_by_scanners=versions_flagged_by_scanners,
        version=version, whiteboard_form=whiteboard_form,
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
    user_key = 'review_viewing_user:{user_id}'.format(user_id=user_id)
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
                               amo.permissions.REVIEWS_ADMIN))
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
    addon_ids = request.GET.get('addon_ids')
    if not addon_ids:
        return {}

    viewing = {}
    user_id = request.user.id

    for addon_id in addon_ids.split(','):
        addon_id = addon_id.strip()
        key = get_reviewing_cache_key(addon_id)
        currently_viewing = cache.get(key)
        if currently_viewing and currently_viewing != user_id:
            viewing[addon_id] = UserProfile.objects.get(
                id=currently_viewing).name

    return viewing


@json_view
@any_reviewer_required
def queue_version_notes(request, addon_id):
    addon = get_object_or_404(Addon.objects, pk=addon_id)
    version = addon.latest_version
    return {'release_notes': str(version.release_notes),
            'approval_notes': version.approval_notes}


@json_view
@any_reviewer_required
def queue_review_text(request, log_id):
    review = get_object_or_404(CommentLog, activity_log_id=log_id)
    return {'reviewtext': review.comments}


@any_reviewer_required
def reviewlog(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = date.today()
        data['start'] = date(today.year, today.month, 1)

    form = ReviewLogForm(data)

    approvals = ActivityLog.objects.review_log()
    if not acl.check_unlisted_addons_reviewer(request):
        # Only display logs related to unlisted versions to users with the
        # right permission.
        list_channel = amo.RELEASE_CHANNEL_LISTED
        approvals = approvals.filter(versionlog__version__channel=list_channel)
    if not acl.check_addons_reviewer(request):
        approvals = approvals.exclude(
            versionlog__version__addon__type__in=amo.GROUP_TYPE_ADDON)
    if not acl.check_static_theme_reviewer(request):
        approvals = approvals.exclude(
            versionlog__version__addon__type=amo.ADDON_STATICTHEME)

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
    data = context(form=form, pager=pager)
    return render(request, 'reviewers/reviewlog.html', data)


@any_reviewer_required
@reviewer_addon_view_factory
def abuse_reports(request, addon):
    developers = addon.listed_authors
    reports = AbuseReport.objects.filter(
        Q(addon=addon) | Q(user__in=developers)
    ).select_related('user').prefetch_related(
        # See review(): we only need the add-on objects and their translations.
        Prefetch('addon', queryset=Addon.objects.all().only_translations()),
    ).order_by('-created')
    reports = amo.utils.paginate(request, reports)
    data = context(addon=addon, reports=reports, version=addon.current_version)
    return render(request, 'reviewers/abuse_reports.html', data)


@any_reviewer_required
def leaderboard(request):
    return render(
        request, 'reviewers/leaderboard.html',
        context(scores=ReviewerScore.all_users_by_score()))


# Permission checks for this view are done inside, depending on type of review
# needed, using perform_review_permission_checks().
@login_required
@reviewer_addon_view_factory
def whiteboard(request, addon, channel):
    channel_as_text = channel
    channel, content_review_only = determine_channel(channel)
    perform_review_permission_checks(
        request, addon, channel, content_review_only=content_review_only)

    whiteboard, _ = Whiteboard.objects.get_or_create(pk=addon.pk)
    form = WhiteboardForm(request.POST or None, instance=whiteboard,
                          prefix='whiteboard')

    if form.is_valid():
        if whiteboard.private or whiteboard.public:
            form.save()
        else:
            whiteboard.delete()

        return redirect('reviewers.review', channel_as_text,
                        addon.slug if addon.slug else addon.pk)
    raise PermissionDenied


@unlisted_addons_reviewer_required
def unlisted_list(request):
    return _queue(request, ViewUnlistedAllListTable, 'all',
                  unlisted=True, SearchForm=AllAddonSearchForm)


def policy_viewer(request, addon, eula_or_privacy, page_title, long_title):
    if not eula_or_privacy:
        raise http.Http404
    channel_text = request.GET.get('channel')
    channel, content_review_only = determine_channel(channel_text)
    # It's a read-only view so we can bypass the specific permissions checks
    # if we have ReviewerTools:View.
    bypass_more_specific_permissions_because_read_only = (
        acl.action_allowed(
            request, amo.permissions.REVIEWER_TOOLS_VIEW))
    if not bypass_more_specific_permissions_because_read_only:
        perform_review_permission_checks(
            request, addon, channel, content_review_only=content_review_only)

    review_url = reverse(
        'reviewers.review',
        args=(channel_text or 'listed',
              addon.slug if addon.slug else addon.pk))
    return render(request, 'reviewers/policy_view.html',
                  {'addon': addon, 'review_url': review_url,
                   'content': eula_or_privacy,
                   'page_title': page_title, 'long_title': long_title})


@login_required
@reviewer_addon_view_factory
def eula(request, addon):
    return policy_viewer(request, addon, addon.eula,
                         page_title=ugettext('{addon} :: EULA'),
                         long_title=ugettext('End-User License Agreement'))


@login_required
@reviewer_addon_view_factory
def privacy(request, addon):
    return policy_viewer(request, addon, addon.privacy_policy,
                         page_title=ugettext('{addon} :: Privacy Policy'),
                         long_title=ugettext('Privacy Policy'))


@any_reviewer_required
@json_view
def theme_background_images(request, version_id):
    """similar to devhub.views.theme_background_image but returns all images"""
    version = get_object_or_404(Version, id=int(version_id))
    return version.get_background_images_encoded(header_only=False)


@login_required
@set_csp(**settings.RESTRICTED_DOWNLOAD_CSP)
def download_git_stored_file(request, version_id, filename):
    version = get_object_or_404(Version.unfiltered, id=int(version_id))

    try:
        addon = version.addon
    except Addon.DoesNotExist:
        raise http.Http404

    if version.channel == amo.RELEASE_CHANNEL_LISTED:
        is_owner = acl.check_addon_ownership(request, addon, dev=True)
        if not (acl.is_reviewer(request, addon) or is_owner):
            raise PermissionDenied
    else:
        if not owner_or_unlisted_reviewer(request, addon):
            raise http.Http404

    file = version.current_file

    serializer = FileEntriesSerializer(
        instance=file, context={
            'file': filename,
            'request': request
        }
    )

    commit = serializer._get_commit(file)
    tree = serializer.repo.get_root_tree(commit)

    try:
        blob_or_tree = tree[serializer.get_selected_file(file)]

        if blob_or_tree.type == pygit2.GIT_OBJ_TREE:
            return http.HttpResponseBadRequest('Can\'t serve directories')
        selected_file = serializer.get_entries(file)[filename]
    except (KeyError, NotFound):
        raise http.Http404()

    actual_blob = serializer.git_repo[blob_or_tree.oid]

    response = http.HttpResponse(
        content=actual_blob.data,
        content_type=selected_file['mimetype'])

    # Backported from Django 2.1 to handle unicode filenames properly
    selected_filename = selected_file['filename']
    try:
        selected_filename.encode('ascii')
        file_expr = 'filename="{}"'.format(selected_filename)
    except UnicodeEncodeError:
        file_expr = "filename*=utf-8''{}".format(urlquote(selected_filename))

    response['Content-Disposition'] = 'attachment; {}'.format(file_expr)
    response['Content-Length'] = actual_blob.size

    return response


class AddonReviewerViewSet(GenericViewSet):
    log = olympia.core.logger.getLogger('z.reviewers')

    @action(
        detail=True,
        methods=['post'], permission_classes=[AllowAnyKindOfReviewer])
    def subscribe(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.get_or_create(
            user=request.user, addon=addon)
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=['post'], permission_classes=[AllowAnyKindOfReviewer])
    def unsubscribe(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.filter(
            user=request.user, addon=addon).delete()
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)])
    def disable(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        addon.force_disable()
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)])
    def enable(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        addon.force_enable()
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=['patch'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)])
    def flags(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        instance, _ = AddonReviewerFlags.objects.get_or_create(addon=addon)
        serializer = AddonReviewerFlagsSerializer(
            instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # If pending info request was modified, log it.
        if 'pending_info_request' in serializer.initial_data:
            ActivityLog.create(amo.LOG.ADMIN_ALTER_INFO_REQUEST, addon)
        serializer.save()
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)])
    def deny_resubmission(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        status_code = status.HTTP_202_ACCEPTED
        try:
            addon.deny_resubmission()
        except RuntimeError:
            status_code = status.HTTP_409_CONFLICT
        return Response(status=status_code)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)])
    def allow_resubmission(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        status_code = status.HTTP_202_ACCEPTED
        try:
            addon.allow_resubmission()
        except RuntimeError:
            status_code = status.HTTP_409_CONFLICT
        return Response(status=status_code)


class ReviewAddonVersionMixin(object):
    permission_classes = [AnyOf(
        AllowReviewer, AllowReviewerUnlisted, AllowAddonAuthor,
    )]

    def get_queryset(self):
        # Permission classes disallow access to non-public/unlisted add-ons
        # unless logged in as a reviewer/addon owner/admin, so we don't have to
        # filter the base queryset here.
        addon = self.get_addon_object()

        qset = (
            Version.unfiltered
            .get_queryset()
            .only_translations()
            .filter(addon=addon)
            .order_by('-created'))

        # Allow viewing unlisted for reviewers with permissions or
        # addon authors.
        can_view_unlisted = (
            acl.check_unlisted_addons_reviewer(self.request) or
            addon.has_author(self.request.user))

        if not can_view_unlisted:
            qset = qset.filter(channel=amo.RELEASE_CHANNEL_LISTED)

        return qset

    def get_addon_object(self):
        return get_object_or_404(
            Addon.objects.get_queryset().only_translations(),
            pk=self.kwargs.get('addon_pk'))

    def get_version_object(self):
        return self.get_object(pk=self.kwargs['version_pk'])

    def get_object(self, **kwargs):
        qset = self.filter_queryset(self.get_queryset())

        kwargs.setdefault(
            self.lookup_field,
            self.kwargs.get(self.lookup_url_kwarg or self.lookup_field))

        obj = get_object_or_404(qset, **kwargs)

        # If the instance is marked as deleted and the client is not allowed to
        # see deleted instances, we want to return a 404, behaving as if it
        # does not exist.
        if obj.deleted and not (
                GroupPermission(amo.permissions.ADDONS_VIEW_DELETED).
                has_object_permission(self.request, self, obj.addon)):
            raise http.Http404

        # Now we can checking permissions
        self.check_object_permissions(self.request, obj)

        return obj

    def check_permissions(self, request):
        if self.action == u'list':
            # When listing DRF doesn't explicitly check for object permissions
            # but here we need to do that against the parent add-on.
            # So we're calling check_object_permission() ourselves,
            # which will pass down the addon object directly.
            return (
                super(ReviewAddonVersionMixin, self)
                .check_object_permissions(request, self.get_addon_object()))

        super(ReviewAddonVersionMixin, self).check_permissions(request)

    def check_object_permissions(self, request, obj):
        """Check permissions against the parent add-on object."""
        return super(ReviewAddonVersionMixin, self).check_object_permissions(
            request, obj.addon)


class ReviewAddonVersionViewSet(ReviewAddonVersionMixin, ListModelMixin,
                                RetrieveModelMixin, GenericViewSet):

    def list(self, request, *args, **kwargs):
        """Return all (re)viewable versions for this add-on.

        Full list, no pagination."""
        qset = self.filter_queryset(self.get_queryset())

        # Smaller performance optimization, only list fields we actually
        # need.
        qset = qset.no_transforms().only(
            *DiffableVersionSerializer.Meta.fields)

        serializer = DiffableVersionSerializer(qset, many=True)

        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        serializer = AddonBrowseVersionSerializer(
            instance=self.get_object(),
            context={
                'file': self.request.GET.get('file', None),
                'request': self.request
            }
        )
        return Response(serializer.data)


class ReviewAddonVersionDraftCommentViewSet(
        RetrieveModelMixin, ListModelMixin, CreateModelMixin,
        DestroyModelMixin, UpdateModelMixin, GenericViewSet):

    permission_classes = [AnyOf(
        AllowReviewer, AllowReviewerUnlisted, AllowAddonAuthor,
    )]

    queryset = DraftComment.objects.all()
    serializer_class = DraftCommentSerializer

    def check_object_permissions(self, request, obj):
        """Check permissions against the parent add-on object."""
        return super().check_object_permissions(request, obj.version.addon)

    def _verify_object_permissions(self, object_to_verify, version):
        """Verify permissions.

        This method works for `Version` and `DraftComment` objects.
        """
        # If the instance is marked as deleted and the client is not allowed to
        # see deleted instances, we want to return a 404, behaving as if it
        # does not exist.
        if version.deleted and not (
                GroupPermission(amo.permissions.ADDONS_VIEW_DELETED).
                has_object_permission(self.request, self, version.addon)):
            raise http.Http404

        # Now we can checking permissions
        super().check_object_permissions(self.request, version.addon)

    def get_queryset(self):
        # Preload version once for all drafts returned, and join with user and
        # canned response to avoid extra queries for those.
        return self.get_version_object().draftcomment_set.all().select_related(
            'user', 'canned_response')

    def get_object(self, **kwargs):
        qset = self.filter_queryset(self.get_queryset())

        kwargs.setdefault(
            self.lookup_field,
            self.kwargs.get(self.lookup_url_kwarg or self.lookup_field))

        obj = get_object_or_404(qset, **kwargs)
        self._verify_object_permissions(obj, obj.version)
        return obj

    def get_addon_object(self):
        if not hasattr(self, 'addon_object'):
            self.addon_object = get_object_or_404(
                # The serializer will not need to return much info about the
                # addon, so we can use just the translations transformer and
                # avoid the rest.
                Addon.objects.get_queryset().only_translations(),
                pk=self.kwargs['addon_pk'])
        return self.addon_object

    def get_version_object(self):
        if not hasattr(self, 'version_object'):
            self.version_object = get_object_or_404(
                # The serializer will need to return a bunch of info about the
                # version, so keep the default transformer.
                self.get_addon_object().versions.all(),
                pk=self.kwargs['version_pk'])
            self._verify_object_permissions(
                self.version_object, self.version_object)
        return self.version_object

    def get_extra_comment_data(self):
        return {
            'version': self.get_version_object().pk,
            'user': self.request.user.pk
        }

    def filter_queryset(self, qset):
        qset = super().filter_queryset(qset)
        # Filter to only show your comments. We're already filtering on version
        # in get_queryset() as starting from the related manager allows us to
        # only load the version once.
        return qset.filter(user=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['version'] = self.get_version_object()
        # Patch in `version` and `user` as those are required by the serializer
        # and not provided by the API client as part of the POST data.
        self.request.data.update(self.get_extra_comment_data())
        return context


class ReviewAddonVersionCompareViewSet(ReviewAddonVersionMixin,
                                       RetrieveModelMixin, GenericViewSet):

    def retrieve(self, request, *args, **kwargs):
        serializer = AddonCompareVersionSerializer(
            instance=self.get_object(),
            context={
                'file': self.request.GET.get('file', None),
                'request': self.request,
                'parent_version': self.get_version_object(),
            })

        return Response(serializer.data)


class CannedResponseViewSet(ListAPIView):
    permission_classes = [AllowAnyKindOfReviewer]

    queryset = CannedResponse.objects.all()
    serializer_class = CannedResponseSerializer
    # The amount of data will be small so that paginating will be
    # overkill and result in unnecessary additional requests
    pagination_class = None

    @classmethod
    def as_view(cls, **initkwargs):
        """The API is read-only so we can turn off atomic requests."""
        return non_atomic_requests(
            super(CannedResponseViewSet, cls).as_view(**initkwargs))
