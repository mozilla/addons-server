from collections import OrderedDict
from datetime import date, datetime
from urllib.parse import urljoin

from django import http
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.db.transaction import non_atomic_requests
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache

from rest_framework import status
from rest_framework.decorators import action as drf_action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger
from olympia import amo
from olympia.abuse.models import AbuseReport, CinderPolicy, ContentDecision
from olympia.abuse.tasks import report_decision_to_cinder_and_notify
from olympia.access import acl
from olympia.activity.models import ActivityLog, CommentLog
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
)
from olympia.amo.decorators import (
    json_view,
    login_required,
    permission_required,
    post_required,
)
from olympia.amo.templatetags.jinja_helpers import numberfmt
from olympia.amo.utils import paginate
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
)
from olympia.api.permissions import (
    AllowAnyKindOfReviewer,
    AllowUnlistedViewerOrReviewer,
    GroupPermission,
)
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.reviewers import (
    HELD_DECISION_CHOICES,
    MAX_VERSIONS_SHOWN_INLINE,
    REVIEWS_PER_PAGE,
    REVIEWS_PER_PAGE_MAX,
    VERSIONS_PER_REVIEW_PAGE,
)
from olympia.devhub import tasks as devhub_tasks
from olympia.files.models import File
from olympia.ratings.models import Rating, RatingFlag
from olympia.scanners.admin import formatted_matched_rules_with_files_and_data
from olympia.stats.decorators import bigquery_api_view
from olympia.stats.utils import (
    VERSION_ADU_LIMIT,
    get_average_daily_users_per_version_from_bigquery,
)
from olympia.users.models import UserProfile
from olympia.versions.models import Version
from olympia.zadmin.models import get_config, set_config

from .decorators import (
    any_reviewer_or_moderator_required,
    any_reviewer_required,
    permission_or_tools_listed_view_required,
    reviewer_addon_view_factory,
)
from .forms import (
    HeldDecisionReviewForm,
    MOTDForm,
    PublicWhiteboardForm,
    RatingFlagFormSet,
    RatingModerationLogForm,
    ReviewForm,
    ReviewLogForm,
    ReviewQueueFilter,
    WhiteboardForm,
)
from .models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewerSubscription,
    Whiteboard,
    clear_reviewing_cache,
    get_flags,
    get_reviewing_cache,
    get_reviewing_cache_key,
    set_reviewing_cache,
)
from .serializers import (
    AddonReviewerFlagsSerializer,
)
from .templatetags.jinja_helpers import to_dom_id
from .utils import (
    ContentReviewTable,
    HeldDecisionQueueTable,
    ModerationQueueTable,
    PendingManualApprovalQueueTable,
    PendingRejectionTable,
    ReviewHelper,
    ThemesQueueTable,
)


def context(**kw):
    ctx = {'motd': get_config(amo.config_keys.REVIEWERS_MOTD)}
    ctx.update(kw)
    return ctx


@permission_or_tools_listed_view_required(amo.permissions.RATINGS_MODERATE)
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

    return TemplateResponse(request, 'reviewers/moderationlog.html', context=data)


@permission_or_tools_listed_view_required(amo.permissions.RATINGS_MODERATE)
def ratings_moderation_log_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.moderation_events(), pk=id)

    review = None
    # I really cannot express the depth of the insanity incarnate in
    # our logging code...
    if len(log.arguments) > 1 and isinstance(log.arguments[1], Rating):
        review = log.arguments[1]

    is_admin = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)

    can_undelete = (
        review and review.deleted and (is_admin or request.user.pk == log.user.pk)
    )

    if request.method == 'POST':
        # A Form seems overkill for this.
        if request.POST['action'] == 'undelete':
            if not can_undelete:
                raise PermissionDenied

            review.undelete()
        return redirect('reviewers.ratings_moderation_log.detail', id)

    data = context(log=log, can_undelete=can_undelete)
    return TemplateResponse(
        request, 'reviewers/moderationlog_detail.html', context=data
    )


@any_reviewer_or_moderator_required
def dashboard(request):
    # The dashboard is divided into sections that depend on what the reviewer
    # has access to, each section having one or more links, each link being
    # defined by a text and an URL. The template will show every link of every
    # section we provide in the context.
    sections = OrderedDict()
    view_all_permissions = [
        amo.permissions.REVIEWER_TOOLS_VIEW,
        amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW,
    ]
    view_all = any(
        acl.action_allowed_for(request.user, perm) for perm in view_all_permissions
    )
    queue_counts = {
        queue.name: queue.get_queryset(request).optimized_count()
        for queue in reviewer_tables_registry.values()
        if queue.show_count_in_dashboard
    }

    if view_all or acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW):
        sections['Manual Review'] = [
            (
                'Manual Review ({0})'.format(queue_counts['queue_extension']),
                reverse('reviewers.queue_extension'),
            ),
            ('Review Log', reverse('reviewers.reviewlog')),
            (
                'Add-on Review Guide',
                'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            ),
        ]
    if view_all or acl.action_allowed_for(
        request.user, amo.permissions.ADDONS_CONTENT_REVIEW
    ):
        sections['Content Review'] = [
            (
                'Content Review ({0})'.format(queue_counts['queue_content_review']),
                reverse('reviewers.queue_content_review'),
            ),
        ]
    if view_all or acl.action_allowed_for(
        request.user, amo.permissions.STATIC_THEMES_REVIEW
    ):
        sections['Themes'] = [
            (
                'Awaiting Review ({0})'.format(queue_counts['queue_theme']),
                reverse('reviewers.queue_theme'),
            ),
            (
                'Review Log',
                reverse('reviewers.reviewlog'),
            ),
            (
                'Theme Review Guide',
                'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            ),
        ]
    if view_all or acl.action_allowed_for(
        request.user, amo.permissions.RATINGS_MODERATE
    ):
        sections['User Ratings Moderation'] = [
            (
                'Ratings Awaiting Moderation ({0})'.format(
                    queue_counts['queue_moderated']
                ),
                reverse('reviewers.queue_moderated'),
            ),
            (
                'Moderated Review Log',
                reverse('reviewers.ratings_moderation_log'),
            ),
            (
                'Moderation Guide',
                'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            ),
        ]
    if view_all or acl.action_allowed_for(
        request.user, amo.permissions.ADDON_REVIEWER_MOTD_EDIT
    ):
        sections['Announcement'] = [
            (
                'Update message of the day',
                reverse('reviewers.motd'),
            ),
        ]
    if view_all or acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN):
        sections['Admin Tools'] = [
            (
                'Add-ons Pending Rejection ({0})'.format(
                    queue_counts['queue_pending_rejection']
                ),
                reverse('reviewers.queue_pending_rejection'),
            ),
        ]
    if view_all or acl.action_allowed_for(
        request.user, amo.permissions.ADDONS_HIGH_IMPACT_APPROVE
    ):
        sections['2nd Level Approval'] = [
            (
                'Held Decisions for 2nd Level Approval ({0})'.format(
                    queue_counts['queue_decisions']
                ),
                reverse('reviewers.queue_decisions'),
            ),
        ]
    return TemplateResponse(
        request,
        'reviewers/dashboard.html',
        context=context(
            **{
                # base_context includes motd.
                'sections': sections
            }
        ),
    )


@permission_required(amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
def motd(request):
    form = None
    form = MOTDForm(initial={'motd': get_config(amo.config_keys.REVIEWERS_MOTD)})
    data = context(form=form)
    return TemplateResponse(request, 'reviewers/motd.html', context=data)


@permission_required(amo.permissions.ADDON_REVIEWER_MOTD_EDIT)
@post_required
def save_motd(request):
    form = MOTDForm(request.POST)
    if form.is_valid():
        set_config('reviewers_review_motd', form.cleaned_data['motd'])
        return redirect(reverse('reviewers.motd'))
    data = context(form=form)
    return TemplateResponse(request, 'reviewers/motd.html', context=data)


def queue(request, tab):
    TableObj = reviewer_tables_registry[tab]

    @permission_or_tools_listed_view_required(TableObj.permission)
    def _queue(request, tab):
        params = {}
        order_by = request.GET.get('sort')
        if order_by is None and hasattr(TableObj, 'default_order_by'):
            order_by = TableObj.default_order_by()
        if order_by is not None:
            params['order_by'] = order_by
        filter_form = ReviewQueueFilter(
            request.GET if 'due_date_reasons' in request.GET else None
        )
        due_date_reasons_choices = None
        if filter_form.is_valid():
            # Build a choices subset from the submitted reasons.
            due_date_reasons_choices = NeedsHumanReview.REASONS.extract_subset(
                *(
                    entry.name
                    for entry in NeedsHumanReview.REASONS
                    if entry.annotation in filter_form.cleaned_data['due_date_reasons']
                )
            )
        qs = TableObj.get_queryset(
            request=request,
            upcoming_due_date_focus=True,
            due_date_reasons_choices=due_date_reasons_choices,
        )
        table = TableObj(data=qs, **params)
        per_page = request.GET.get('per_page', REVIEWS_PER_PAGE)
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = REVIEWS_PER_PAGE
        if per_page <= 0 or per_page > REVIEWS_PER_PAGE_MAX:
            per_page = REVIEWS_PER_PAGE
        page = paginate(
            request, table.rows, per_page=per_page, count=qs.optimized_count()
        )

        return TemplateResponse(
            request,
            'reviewers/queue.html',
            context=context(
                page=page,
                registry=reviewer_tables_registry,
                filter_form=filter_form,
                tab=tab,
                table=table,
                title=TableObj.title,
            ),
        )

    return _queue(request, tab)


@permission_or_tools_listed_view_required(amo.permissions.RATINGS_MODERATE)
def queue_moderated(request, tab):
    TableObj = reviewer_tables_registry[tab]
    qs = TableObj.get_queryset(request)
    page = paginate(request, qs, per_page=20)

    flags = dict(RatingFlag.FLAGS)

    reviews_formset = RatingFlagFormSet(
        request.POST or None, queryset=page.object_list, request=request
    )

    if request.method == 'POST':
        if reviews_formset.is_valid():
            reviews_formset.save()
        else:
            amo.messages.error(
                request,
                ' '.join(
                    e.as_text() or 'An unknown error occurred'
                    for e in reviews_formset.errors
                ),
            )
        return redirect(reverse('reviewers.queue_moderated'))

    return TemplateResponse(
        request,
        'reviewers/queue.html',
        context=context(
            reviews_formset=reviews_formset,
            tab=tab,
            page=page,
            flags=flags,
            registry=reviewer_tables_registry,
            title=TableObj.title,
        ),
    )


reviewer_tables_registry = {
    table.name: table
    for table in (
        PendingManualApprovalQueueTable,
        ThemesQueueTable,
        ModerationQueueTable,
        ContentReviewTable,
        PendingRejectionTable,
        HeldDecisionQueueTable,
    )
}


def determine_channel(channel_as_text):
    """Determine which channel the review is for according to the channel
    parameter as text, and whether we should be in content-review only mode."""
    if channel_as_text == 'content':
        # 'content' is not a real channel, just a different review mode for
        # listed add-ons.
        content_review = True
        channel = 'listed'
    else:
        content_review = False
    # channel is passed in as text, but we want the constant.
    channel = amo.CHANNEL_CHOICES_LOOKUP.get(channel_as_text, amo.CHANNEL_LISTED)
    return channel, content_review


@login_required
@any_reviewer_required  # Additional permission checks are done inside.
@reviewer_addon_view_factory
def review(request, addon, channel=None):
    whiteboard_url = reverse(
        'reviewers.whiteboard',
        args=(channel or 'listed', addon.pk),
    )
    channel, content_review = determine_channel(channel)

    is_static_theme = addon.type == amo.ADDON_STATICTHEME
    promoted_groups = addon.promoted_groups(currently_approved=False)

    # Are we looking at an unlisted review page, or (weirdly) the listed
    # review page of an unlisted-only add-on?
    unlisted_only = channel == amo.CHANNEL_UNLISTED or not addon.has_listed_versions(
        include_deleted=True
    )
    if unlisted_only and not acl.is_unlisted_addons_viewer_or_reviewer(request.user):
        raise PermissionDenied

    # Are we looking at a listed review page while only having content review
    # permissions ? Redirect to content review page, it will be more useful.
    if (
        channel == amo.CHANNEL_LISTED
        and content_review is False
        and acl.action_allowed_for(request.user, amo.permissions.ADDONS_CONTENT_REVIEW)
        and not acl.is_reviewer(request.user, addon, allow_content_reviewers=False)
    ):
        return redirect('reviewers.review', 'content', addon.pk)

    # Other cases are handled in ReviewHelper by limiting what actions are
    # available depending on user permissions and add-on/version state.
    is_admin = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)
    can_view_source = acl.action_allowed_for(
        request.user, amo.permissions.ADDONS_SOURCE_DOWNLOAD
    )
    version = addon.find_latest_version(channel=channel, exclude=(), deleted=is_admin)
    latest_not_disabled_version = addon.find_latest_version(channel=channel)

    if not settings.ALLOW_SELF_REVIEWS and addon.has_author(request.user):
        amo.messages.warning(request, 'Self-reviews are not allowed.')
        return redirect(reverse('reviewers.dashboard'))

    needs_human_review_qs = NeedsHumanReview.objects.filter(
        is_active=True, version=OuterRef('pk')
    )
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
        .select_related('reviewerflags')
        .select_related('file___webext_permissions')
        .select_related('blockversion')
        # Prefetch needshumanreview existence into a property that the
        # VersionsChoiceWidget will use.
        .annotate(needs_human_review=Exists(needs_human_review_qs))
        # Prefetch scanner results and related rules...
        .prefetch_related('scannerresults')
        .prefetch_related('scannerresults__matched_rules')
        # Add activity transformer to prefetch all related activity logs on
        # top of the regular transformers.
        .transform(Version.transformer_activity)
        # Add auto_approvable transformer to prefetch information about whether
        # each version is auto-approvable or not.
        .transform(Version.transformer_auto_approvable)
    )
    form_helper = ReviewHelper(
        addon=addon,
        version=version,
        user=request.user,
        content_review=content_review,
        human_review=True,
        channel=channel,
    )
    form = ReviewForm(
        request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None,
        helper=form_helper,
    )

    reports = Paginator(AbuseReport.objects.for_addon(addon), 5).page(1)
    user_ratings = Paginator(
        (
            Rating.without_replies.filter(
                addon=addon, rating__lte=3, body__isnull=False
            ).order_by('-created')
        ),
        5,
    ).page(1)
    if channel == amo.CHANNEL_LISTED and is_static_theme:
        redirect_url = reverse('reviewers.queue_theme')
    else:
        channel_arg = (
            amo.CHANNEL_CHOICES_API.get(channel) if not content_review else 'content'
        )
        redirect_url = reverse('reviewers.review', args=[channel_arg, addon.pk])

    if request.method == 'POST' and form.is_valid():
        # Execute the action (is_valid() ensures the action is available to the
        # reviewer)
        form.helper.process()

        amo.messages.success(request, 'Review successfully processed.')
        clear_reviewing_cache(addon.id)
        return redirect(form.helper.redirect_url or redirect_url)

    # Kick off validation tasks for any files in this version which don't have
    # cached validation, since reviewers will almost certainly need to access
    # them. But only if we're not running in eager mode, since that could mean
    # blocking page load for several minutes.
    if version and not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        if not version.file.has_been_validated:
            devhub_tasks.validate(version.file)

    actions = form.helper.actions.items()

    # Find the previously approved version to compare to.
    base_version_pk = version and (
        addon.versions.exclude(id=version.id)
        .filter(
            # We're looking for a version that was either manually approved
            # (either it has no auto approval summary, or it has one but
            # with a negative verdict because it was locked by a reviewer
            # who then approved it themselves), or auto-approved but then
            # confirmed.
            Q(autoapprovalsummary__isnull=True)
            | Q(autoapprovalsummary__verdict=amo.NOT_AUTO_APPROVED)
            | Q(
                autoapprovalsummary__verdict=amo.AUTO_APPROVED,
                autoapprovalsummary__confirmed=True,
            )
        )
        .filter(
            channel=channel,
            file__isnull=False,
            created__lt=version.created,
            file__status=amo.STATUS_APPROVED,
        )
        .values_list('pk', flat=True)
        .order_by('-created')
        .first()
    )
    # The actions we shouldn't show a minimal form for.
    actions_full = []
    # The actions we should show the comments form for (contrary to minimal
    # form above, it defaults to True, because most actions do need to have
    # the comments form).
    actions_comments = []
    # The actions for which we should display the delayed rejection fields.
    actions_delayable = []
    # The actions for which we should display the reason select field.
    actions_reasons = []
    # The actions for which we should display the resolve abuse reports checkbox
    actions_resolves_cinder_jobs = []
    # The actions for which we should display the cinder policy select field.
    actions_policies = []
    # The actions for which to allow attachments.
    actions_attachments = []

    for key, action in actions:
        if not (is_static_theme or action.get('minimal')):
            actions_full.append(key)
        if action.get('comments', True):
            actions_comments.append(key)
        if action.get('delayable', False):
            actions_delayable.append(key)
        if action.get('allows_reasons', False):
            actions_reasons.append(key)
        if action.get('enforcement_actions'):
            actions_policies.append(key)
        if action.get('resolves_cinder_jobs', False):
            actions_resolves_cinder_jobs.append(key)
        if action.get('can_attach', True):
            actions_attachments.append(key)

    addons_sharing_same_guid = (
        Addon.unfiltered.all()
        .only_translations()
        .filter(addonguid__guid=addon.addonguid_guid)
        .exclude(pk=addon.pk)
        .order_by('pk')
        if addon.addonguid_guid
        else []
    )
    approvals_info = None
    if (
        channel == amo.CHANNEL_LISTED
        and addon.current_version
        and addon.current_version.was_auto_approved
    ):
        try:
            approvals_info = addon.addonapprovalscounter
        except AddonApprovalsCounter.DoesNotExist:
            pass

    pager = paginate(request, versions_qs, VERSIONS_PER_REVIEW_PAGE)
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

    versions_pending_rejection_qs = versions_qs.filter(
        reviewerflags__pending_rejection__isnull=False
    )
    # We want to notify the reviewer if there are versions needing extra
    # attention that are not present in the versions history (which is
    # paginated).
    versions_with_a_due_date_other = (
        versions_qs.filter(due_date__isnull=False).exclude(pk__in=version_ids).count()
    )
    versions_pending_rejection_other = versions_pending_rejection_qs.exclude(
        pk__in=version_ids
    ).count()

    # if the add-on was force-disabled we want to inform the reviewer what versions will
    # be re-enabled automatically by a force enable action. (in all channels)
    versions_that_would_be_enabled = (
        ()
        if addon.status != amo.STATUS_DISABLED
        else File.objects.disabled_that_would_be_renabled_with_addon()
        .filter(version__addon=addon)
        .order_by('-created')
        .values_list(
            'version__version', 'original_status', 'version__channel', named=True
        )
    )

    flags = get_flags(addon, version) if version else []

    try:
        whiteboard = Whiteboard.objects.get(pk=addon.pk)
    except Whiteboard.DoesNotExist:
        whiteboard = Whiteboard(pk=addon.pk)

    wb_form_cls = PublicWhiteboardForm if is_static_theme else WhiteboardForm
    whiteboard_form = wb_form_cls(instance=whiteboard, prefix='whiteboard')

    # Actions that are not tied to a specific version that we want to highlight
    # in the "Add-on important changes history" section.
    important_changes_log = ActivityLog.objects.filter(
        action__in=amo.LOG_REVIEW_QUEUE_IMPORTANT_CHANGE,
        addonlog__addon=addon,
    ).order_by('id')

    name_translations = (
        addon.name.__class__.objects.filter(
            id=addon.name.id, localized_string__isnull=False
        ).exclude(localized_string='')
        if addon.name
        else []
    )

    Addon._attach_authors([addon], listed=None, to_attr='current_authors')

    ctx = context(
        # Used for reviewer subscription check, don't use global `is_reviewer`
        # since that actually is `is_user_any_kind_of_reviewer`.
        acl_is_reviewer=acl.is_reviewer(request.user, addon),
        acl_is_unlisted_addons_viewer_or_reviewer=(
            acl.is_unlisted_addons_viewer_or_reviewer(request.user)
        ),
        acl_is_review_moderator=(
            acl.action_allowed_for(request.user, amo.permissions.RATINGS_MODERATE)
            and request.user.is_staff
        ),
        actions=actions,
        actions_attachments=actions_attachments,
        actions_comments=actions_comments,
        actions_delayable=actions_delayable,
        actions_full=actions_full,
        actions_policies=actions_policies,
        actions_reasons=actions_reasons,
        actions_resolves_cinder_jobs=actions_resolves_cinder_jobs,
        addon=addon,
        addons_sharing_same_guid=addons_sharing_same_guid,
        approvals_info=approvals_info,
        auto_approval_info=auto_approval_info,
        base_version_pk=base_version_pk,
        can_view_source=can_view_source,
        channel=channel,
        content_review=content_review,
        count=count,
        flags=flags,
        form=form,
        format_matched_rules=formatted_matched_rules_with_files_and_data,
        has_versions_with_due_date_in_other_channel=addon.versions(
            manager='unfiltered_for_relations'
        )
        .exclude(channel=channel)
        .filter(due_date__isnull=False)
        .exists(),
        important_changes_log=important_changes_log,
        is_admin=is_admin,
        language_dict=dict(settings.LANGUAGES),
        latest_not_disabled_version=latest_not_disabled_version,
        latest_version_is_unreviewed_and_not_pending_rejection=(
            version
            and version.channel == amo.CHANNEL_LISTED
            and version.is_unreviewed
            and not version.pending_rejection
        ),
        promoted_groups=promoted_groups,
        name_translations=name_translations,
        now=datetime.now(),
        num_pages=num_pages,
        pager=pager,
        reports=reports,
        session_id=request.session.session_key,
        subscribed_listed=ReviewerSubscription.objects.filter(
            user=request.user, addon=addon, channel=amo.CHANNEL_LISTED
        ).exists(),
        subscribed_unlisted=ReviewerSubscription.objects.filter(
            user=request.user, addon=addon, channel=amo.CHANNEL_UNLISTED
        ).exists(),
        unlisted=(channel == amo.CHANNEL_UNLISTED),
        user_ratings=user_ratings,
        version=version,
        VERSION_ADU_LIMIT=VERSION_ADU_LIMIT,
        versions_that_would_be_enabled=versions_that_would_be_enabled,
        MAX_VERSIONS_SHOWN_INLINE=MAX_VERSIONS_SHOWN_INLINE,
        versions_with_a_due_date_other=versions_with_a_due_date_other,
        versions_pending_rejection_other=versions_pending_rejection_other,
        whiteboard_form=whiteboard_form,
        whiteboard_url=whiteboard_url,
    )
    return TemplateResponse(request, 'reviewers/review.html', context=ctx)


@never_cache
@json_view
# This will 403 for users with only ReviewerTools:View, but they shouldn't
# acquire reviewer locks anyway, and it's not a big deal if they don't see
# existing locks.
@any_reviewer_required
def review_viewing(request):
    if 'addon_id' not in request.POST:
        return {}

    addon_id = request.POST['addon_id']
    user_id = request.user.id
    current_name = ''
    is_user = 0
    key = get_reviewing_cache_key(addon_id)
    user_key = f'review_viewing_user:{user_id}'
    interval = amo.REVIEWER_VIEWING_INTERVAL

    # Check who is viewing.
    currently_viewing = get_reviewing_cache(addon_id)

    # If nobody is viewing or current user is, set current user as viewing
    if not currently_viewing or currently_viewing == user_id:
        # Get a list of all the reviews this user is locked on.
        review_locks = cache.get_many(cache.get(user_key, {}))
        can_lock_more_reviews = len(
            review_locks
        ) < amo.REVIEWER_REVIEW_LOCK_LIMIT or acl.action_allowed_for(
            request.user, amo.permissions.REVIEWS_ADMIN
        )
        if can_lock_more_reviews or currently_viewing == user_id:
            set_reviewing_cache(addon_id, user_id)
            # Give it double expiry just to be safe.
            cache.set(user_key, set(review_locks) | {key}, interval * 4)
            currently_viewing = user_id
            current_name = request.user.name
            is_user = 1
        else:
            currently_viewing = settings.TASK_USER_ID
            current_name = 'Review lock limit reached'
            is_user = 2
    else:
        current_name = UserProfile.objects.get(pk=currently_viewing).name

    return {
        'current': currently_viewing,
        'current_name': current_name,
        'is_user': is_user,
    }


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
            viewing[addon_id] = UserProfile.objects.get(id=currently_viewing).name

    return viewing


@json_view
@any_reviewer_required
def queue_version_notes(request, addon_id):
    addon = get_object_or_404(Addon.objects, pk=addon_id)
    version = addon.latest_version
    return {
        'release_notes': str(version.release_notes),
        'approval_notes': version.approval_notes,
    }


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

    qs = ActivityLog.objects.review_log()
    if not acl.is_unlisted_addons_viewer_or_reviewer(request.user):
        # Only display logs related to unlisted versions to users with the
        # right permission.
        qs = qs.exclude(versionlog__version__channel=amo.CHANNEL_UNLISTED)
    if not acl.is_listed_addons_reviewer(request.user):
        qs = qs.exclude(versionlog__version__addon__type__in=amo.GROUP_TYPE_ADDON)
    if not acl.is_static_theme_reviewer(request.user):
        qs = qs.exclude(versionlog__version__addon__type=amo.ADDON_STATICTHEME)

    if form.is_valid():
        data = form.cleaned_data
        if data['start']:
            qs = qs.filter(created__gte=data['start'])
        if data['end']:
            qs = qs.filter(created__lt=data['end'])
        if data['search']:
            term = data['search']
            qs = qs.filter(
                Q(commentlog__comments__icontains=term)
                | Q(addonlog__addon__name__localized_string__icontains=term)
                | Q(user__display_name__icontains=term)
                | Q(user__username__icontains=term)
            ).distinct()

    pager = amo.utils.paginate(request, qs, 50)
    data = context(form=form, pager=pager)
    return TemplateResponse(request, 'reviewers/reviewlog.html', context=data)


@any_reviewer_required
@reviewer_addon_view_factory
def abuse_reports(request, addon):
    reports = amo.utils.paginate(request, AbuseReport.objects.for_addon(addon))
    data = context(addon=addon, reports=reports, version=addon.current_version)
    return TemplateResponse(request, 'reviewers/abuse_reports.html', context=data)


@any_reviewer_required
@reviewer_addon_view_factory
def whiteboard(request, addon, channel):
    channel_as_text = channel
    channel, content_review = determine_channel(channel)

    unlisted_only = channel == amo.CHANNEL_UNLISTED or not addon.has_listed_versions(
        include_deleted=True
    )
    if unlisted_only and not acl.is_unlisted_addons_viewer_or_reviewer(request.user):
        raise PermissionDenied

    whiteboard, _ = Whiteboard.objects.get_or_create(pk=addon.pk)
    form = WhiteboardForm(
        request.POST or None, instance=whiteboard, prefix='whiteboard'
    )

    if form.is_valid():
        if whiteboard.private or whiteboard.public:
            form.save()
        else:
            whiteboard.delete()

        return redirect('reviewers.review', channel_as_text, addon.pk)
    raise PermissionDenied


def policy_viewer(request, addon, eula_or_privacy, page_title, long_title):
    unlisted_only = not addon.has_listed_versions(include_deleted=True)
    if unlisted_only and not acl.is_unlisted_addons_viewer_or_reviewer(request.user):
        raise PermissionDenied

    if not eula_or_privacy:
        raise http.Http404
    channel_text = request.GET.get('channel')
    channel, content_review = determine_channel(channel_text)

    review_url = reverse(
        'reviewers.review',
        args=(channel_text or 'listed', addon.pk),
    )
    return TemplateResponse(
        request,
        'reviewers/policy_view.html',
        context={
            'addon': addon,
            'review_url': review_url,
            'content': eula_or_privacy,
            'page_title': page_title,
            'long_title': long_title,
        },
    )


@any_reviewer_required
@reviewer_addon_view_factory
def eula(request, addon):
    return policy_viewer(
        request,
        addon,
        addon.eula,
        page_title='{addon} – EULA',
        long_title='End-User License Agreement',
    )


@any_reviewer_required
@reviewer_addon_view_factory
def privacy(request, addon):
    return policy_viewer(
        request,
        addon,
        addon.privacy_policy,
        page_title='{addon} – Privacy Policy',
        long_title='Privacy Policy',
    )


@any_reviewer_required
@json_view
def theme_background_images(request, version_id):
    """similar to devhub.views.theme_background_image but returns all images"""
    version = get_object_or_404(Version, id=int(version_id))
    return version.get_background_images_encoded(header_only=False)


@any_reviewer_required
def developer_profile(request, user_id):
    developer = get_object_or_404(UserProfile, id=user_id)
    qs = AddonUser.unfiltered.filter(user=developer).order_by('addon_id')
    addonusers_pager = paginate(request, qs, 100)

    return TemplateResponse(
        request,
        'reviewers/developer_profile.html',
        context={
            'is_user_admin': acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT),
            'developer': developer,
            'addonusers_pager': addonusers_pager,
        },
    )


class AddonReviewerViewSet(GenericViewSet):
    log = olympia.core.logger.getLogger('z.reviewers')
    lookup_value_regex = r'\d+'

    @drf_action(
        detail=True, methods=['post'], permission_classes=[AllowAnyKindOfReviewer]
    )
    def subscribe(self, request, **kwargs):
        return self.subscribe_listed(request, **kwargs)

    @drf_action(
        detail=True, methods=['post'], permission_classes=[AllowAnyKindOfReviewer]
    )
    def subscribe_listed(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.get_or_create(
            user=request.user, addon=addon, channel=amo.CHANNEL_LISTED
        )
        return Response(status=status.HTTP_202_ACCEPTED)

    @drf_action(
        detail=True, methods=['post'], permission_classes=[AllowAnyKindOfReviewer]
    )
    def unsubscribe(self, request, **kwargs):
        return self.unsubscribe_listed(request, **kwargs)

    @drf_action(
        detail=True, methods=['post'], permission_classes=[AllowAnyKindOfReviewer]
    )
    def unsubscribe_listed(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.filter(
            user=request.user, addon=addon, channel=amo.CHANNEL_LISTED
        ).delete()
        return Response(status=status.HTTP_202_ACCEPTED)

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[AllowUnlistedViewerOrReviewer],
    )
    def subscribe_unlisted(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.get_or_create(
            user=request.user, addon=addon, channel=amo.CHANNEL_UNLISTED
        )
        return Response(status=status.HTTP_202_ACCEPTED)

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[AllowUnlistedViewerOrReviewer],
    )
    def unsubscribe_unlisted(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        ReviewerSubscription.objects.filter(
            user=request.user, addon=addon, channel=amo.CHANNEL_UNLISTED
        ).delete()
        return Response(status=status.HTTP_202_ACCEPTED)

    @drf_action(
        detail=True,
        methods=['patch'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)],
    )
    def flags(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        instance, _ = AddonReviewerFlags.objects.get_or_create(addon=addon)
        serializer = AddonReviewerFlagsSerializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)],
    )
    def deny_resubmission(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        status_code = status.HTTP_202_ACCEPTED
        try:
            addon.deny_resubmission()
        except RuntimeError:
            status_code = status.HTTP_409_CONFLICT
        return Response(status=status_code)

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)],
    )
    def allow_resubmission(self, request, **kwargs):
        addon = get_object_or_404(Addon, pk=kwargs['pk'])
        status_code = status.HTTP_202_ACCEPTED
        try:
            addon.allow_resubmission()
        except RuntimeError:
            status_code = status.HTTP_409_CONFLICT
        return Response(status=status_code)

    @drf_action(
        detail=True,
        methods=['get'],
        permission_classes=[AllowAnyKindOfReviewer],
        authentication_classes=[
            JWTKeyAuthentication,
            SessionIDAuthentication,
        ],
        url_path=r'file/(?P<file_id>[^/]+)/validation',
    )
    def json_file_validation(self, request, **kwargs):
        addon = get_object_or_404(Addon.unfiltered.id_or_slug(kwargs['pk']))
        file = get_object_or_404(File, version__addon=addon, id=kwargs['file_id'])
        if file.version.channel == amo.CHANNEL_UNLISTED:
            if not acl.is_unlisted_addons_viewer_or_reviewer(request.user):
                raise PermissionDenied
        elif not acl.is_reviewer(request.user, addon):
            raise PermissionDenied
        try:
            result = file.validation
        except File.validation.RelatedObjectDoesNotExist as exc:
            raise http.Http404 from exc
        return JsonResponse(
            {
                'validation': result.processed_validation,
            }
        )

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)],
    )
    def due_date(self, request, **kwargs):
        version = get_object_or_404(
            Version, pk=request.data.get('version'), addon_id=kwargs['pk']
        )
        status_code = status.HTTP_202_ACCEPTED
        try:
            due_date = datetime.fromisoformat(request.data.get('due_date'))
            version.reset_due_date(due_date=due_date)
        except TypeError:
            status_code = status.HTTP_400_BAD_REQUEST
        return Response(status=status_code)

    @drf_action(
        detail=True,
        methods=['post'],
        permission_classes=[GroupPermission(amo.permissions.REVIEWS_ADMIN)],
    )
    def set_needs_human_review(self, request, **kwargs):
        version = get_object_or_404(
            Version, pk=request.data.get('version'), addon_id=kwargs['pk']
        )
        status_code = status.HTTP_202_ACCEPTED
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        due_date = version.reload().due_date
        due_date_string = due_date.isoformat(timespec='seconds') if due_date else None
        return Response(status=status_code, data={'due_date': due_date_string})


@bigquery_api_view(json_default=dict)
@any_reviewer_required
@reviewer_addon_view_factory
@non_atomic_requests
def usage_per_version(request, addon):
    versions_avg = get_average_daily_users_per_version_from_bigquery(addon)
    response = JsonResponse(
        {'adus': [[version, numberfmt(adu)] for (version, adu) in versions_avg]}
    )
    patch_cache_control(response, max_age=5 * 60)
    return response


@any_reviewer_required
@reviewer_addon_view_factory
@non_atomic_requests
def review_version_redirect(request, addon, version):
    addon_versions = addon.versions(manager='unfiltered_for_relations').values_list(
        'version', 'channel'
    )

    def index_in_versions_list(channel, value):
        versions = (ver for ver, chan in addon_versions if chan == channel)
        for idx, ver in enumerate(versions):
            if value == ver:
                return idx
        return None

    # Check each channel to calculate which # it would be in a list of versions
    for channel, channel_text in amo.CHANNEL_CHOICES_API.items():  # noqa: B007
        if (index := index_in_versions_list(channel, version)) is not None:
            break
    else:
        raise http.Http404

    page_param = (
        f'?page={page + 1}' if (page := index // VERSIONS_PER_REVIEW_PAGE) else ''
    )
    url = reverse('reviewers.review', args=(channel_text, addon.pk))
    return redirect(url + page_param + f'#version-{to_dom_id(version)}')


@permission_or_tools_listed_view_required(amo.permissions.ADDONS_HIGH_IMPACT_APPROVE)
def queue_decisions(request, tab):
    TableObj = reviewer_tables_registry[tab]
    qs = TableObj.get_queryset(request)
    page = paginate(request, qs, per_page=20)

    return TemplateResponse(
        request,
        'reviewers/queue.html',
        context=context(
            tab=tab,
            page=page,
            registry=reviewer_tables_registry,
            title=TableObj.title,
        ),
    )


@permission_or_tools_listed_view_required(amo.permissions.ADDONS_HIGH_IMPACT_APPROVE)
def decision_review(request, decision_id):
    decision = get_object_or_404(ContentDecision, pk=decision_id)
    form = HeldDecisionReviewForm(
        request.POST if request.method == 'POST' else None, decision=decision
    )
    if form.is_valid():
        data = form.cleaned_data
        match data.get('choice'):
            case HELD_DECISION_CHOICES.YES:
                decision.execute_action(release_hold=True)
                decision.send_notifications()
            case HELD_DECISION_CHOICES.NO:
                new_decision = ContentDecision.objects.create(
                    addon=decision.addon,
                    rating=decision.rating,
                    collection=decision.collection,
                    user=decision.user,
                    action=DECISION_ACTIONS.AMO_APPROVE,
                    reviewer_user=request.user,
                    override_of=decision,
                    cinder_job=decision.cinder_job,
                )
                new_decision.policies.set(
                    CinderPolicy.objects.filter(
                        enforcement_actions__in=DECISION_ACTIONS.AMO_APPROVE.api_value
                    )
                )
                new_decision.execute_action(release_hold=True)
                new_decision.target_versions.set(decision.target_versions.all())
                report_decision_to_cinder_and_notify.delay(decision_id=new_decision.id)
            case HELD_DECISION_CHOICES.CANCEL:
                decision.requeue_held_action(
                    user=request.user, notes=data.get('comments', '')
                )

        return redirect('reviewers.queue_decisions')
    return TemplateResponse(
        request,
        'reviewers/decision_review.html',
        context=context(
            cinder_url=urljoin(
                settings.CINDER_SERVER_URL, f'/decision/{decision.cinder_id}'
            ),
            decision=decision,
            form=form,
        ),
    )
