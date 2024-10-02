from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.core.files.base import ContentFile
from django.db.models import Count, F, Q
from django.urls import reverse
from django.utils.http import urlencode

import django_tables2 as tables
import markupsafe

import olympia.core.logger
from olympia import amo
from olympia.abuse.models import CinderJob, CinderPolicy
from olympia.abuse.tasks import notify_addon_decision_to_cinder, resolve_job_in_cinder
from olympia.access import acl
from olympia.activity.models import ActivityLog, AttachmentLog
from olympia.activity.utils import notify_about_activity_log
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import RECOMMENDED
from olympia.lib.crypto.signing import sign_file
from olympia.reviewers.models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    get_flags,
)
from olympia.users.utils import get_task_user
from olympia.versions.models import VersionReviewerFlags


log = olympia.core.logger.getLogger('z.mailer')


def is_admin_reviewer(user):
    return acl.action_allowed_for(user, amo.permissions.REVIEWS_ADMIN)


class AddonQueueTable(tables.Table):
    addon_name = tables.Column(
        verbose_name='Add-on', accessor='name', orderable=False, empty_values=()
    )
    # Override empty_values for flags so that they can be displayed even if the
    # model does not have a flags attribute.
    flags = tables.Column(verbose_name='Flags', empty_values=(), orderable=False)
    last_human_review = tables.DateTimeColumn(
        verbose_name='Last Review',
        accessor='addonapprovalscounter__last_human_review',
    )
    show_count_in_dashboard = True
    view_name = 'queue'

    class Meta:
        fields = (
            'addon_name',
            'flags',
            'last_human_review',
        )
        orderable = False

    def get_version(self, record):
        return record.current_version

    def render_flags_classes(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags(record, self.get_version(record))
        return ' '.join(flag[0] for flag in record.flags)

    def render_flags(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags(record, self.get_version(record))
        return markupsafe.Markup(
            ''.join(
                '<div class="app-icon ed-sprite-%s" title="%s"></div>' % flag
                for flag in record.flags
            )
        )

    def _get_addon_name_url(self, record):
        args = [record.id]
        if self.get_version(record).channel == amo.CHANNEL_UNLISTED:
            args.insert(0, 'unlisted')
        return reverse('reviewers.review', args=args)

    def render_addon_name(self, record):
        url = self._get_addon_name_url(record)
        name = markupsafe.escape(str(record.name or '').strip() or f'[{record.id}]')
        return markupsafe.Markup(
            '<a href="%s">%s <em>%s</em></a>'
            % (url, name, markupsafe.escape(self.get_version(record).version))
        )

    def render_last_human_review(self, value):
        return naturaltime(value) if value else ''

    render_last_content_review = render_last_human_review


class PendingManualApprovalQueueTable(AddonQueueTable):
    addon_type = tables.Column(verbose_name='Type', accessor='type', orderable=False)
    due_date = tables.Column(verbose_name='Due Date', accessor='first_version_due_date')
    title = '🛠️ Manual Review'
    urlname = 'queue_extension'
    url = r'^extension$'
    permission = amo.permissions.ADDONS_REVIEW

    class Meta(AddonQueueTable.Meta):
        fields = ('addon_name', 'addon_type', 'due_date', 'flags')
        exclude = ('last_human_review',)
        orderable = True

    @classmethod
    def get_queryset(self, request, *, upcoming_due_date_focus=False, **kw):
        show_only_upcoming = upcoming_due_date_focus and not acl.action_allowed_for(
            request.user, amo.permissions.ADDONS_ALL_DUE_DATES
        )
        qs = Addon.unfiltered.get_queryset_for_pending_queues(
            admin_reviewer=is_admin_reviewer(request.user),
            show_temporarily_delayed=acl.action_allowed_for(
                request.user, amo.permissions.ADDONS_TRIAGE_DELAYED
            ),
            show_only_upcoming=show_only_upcoming,
        )
        return qs

    def get_version(self, record):
        # Use the property set by get_queryset_for_pending_queues() to display
        # the right version.
        return record.first_pending_version

    def render_addon_type(self, record):
        return record.get_type_display()

    def render_due_date(self, record):
        due_date = self.get_version(record).due_date
        return markupsafe.Markup(
            f'<span title="{markupsafe.escape(due_date)}">'
            f'{markupsafe.escape(naturaltime(due_date))}</span>'
        )

    @classmethod
    def default_order_by(cls):
        # We want to display the add-ons which have earliest due date at the top by
        # default, so we return due_date in ascending order.
        return 'due_date'


class ThemesQueueTable(PendingManualApprovalQueueTable):
    title = '🎨 Themes'
    urlname = 'queue_theme'
    url = r'^theme$'
    permission = amo.permissions.STATIC_THEMES_REVIEW
    due_date = tables.Column(
        verbose_name='Target Date', accessor='first_version_due_date'
    )

    class Meta(PendingManualApprovalQueueTable.Meta):
        exclude = (
            'addon_type',
            'last_human_review',
        )

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_queryset_for_pending_queues(
            admin_reviewer=is_admin_reviewer(request.user), theme_review=True
        )


class PendingRejectionTable(AddonQueueTable):
    deadline = tables.Column(
        verbose_name='Pending Rejection Deadline',
        accessor='first_version_pending_rejection_date',
    )
    title = 'Pending Rejection'
    urlname = 'queue_pending_rejection'
    url = r'^pending_rejection$'
    permission = amo.permissions.REVIEWS_ADMIN

    class Meta(PendingManualApprovalQueueTable.Meta):
        fields = (
            'addon_name',
            'flags',
            'last_human_review',
            'deadline',
        )
        exclude = ('due_date',)

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_pending_rejection_queue(
            admin_reviewer=is_admin_reviewer(request.user)
        )

    def get_version(self, record):
        # Use the property set by get_pending_rejection_queue() to display
        # the right version.
        return record.first_pending_version

    def render_deadline(self, value):
        return naturaltime(value) if value else ''


class ContentReviewTable(AddonQueueTable):
    last_updated = tables.DateTimeColumn(verbose_name='Last Updated')
    title = 'Content Review'
    urlname = 'queue_content_review'
    url = r'^content_review$'
    permission = amo.permissions.ADDONS_CONTENT_REVIEW

    class Meta(AddonQueueTable.Meta):
        fields = ('addon_name', 'flags', 'last_updated')
        # Exclude base fields AddonQueueTable has that we don't want.
        exclude = ('last_human_review',)
        orderable = False

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_content_review_queue(
            admin_reviewer=is_admin_reviewer(request.user)
        )

    def render_last_updated(self, value):
        return naturaltime(value) if value else ''

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=['content', record.id])


class MadReviewTable(AddonQueueTable):
    listed_text = 'Listed version'
    unlisted_text = 'Unlisted versions ({0})'
    show_count_in_dashboard = False
    title = 'Flagged by MAD for Human Review'
    urlname = 'queue_mad'
    url = r'^mad$'
    permission = amo.permissions.ADDONS_REVIEW

    def render_addon_name(self, record):
        rval = [markupsafe.escape(record.name)]

        if record.listed_versions_that_need_human_review:
            url = reverse('reviewers.review', args=[record.id])
            rval.append(
                '<a href="%s">%s</a>'
                % (
                    url,
                    self.listed_text.format(
                        record.listed_versions_that_need_human_review
                    ),
                )
            )

        if record.unlisted_versions_that_need_human_review:
            url = reverse('reviewers.review', args=['unlisted', record.id])
            rval.append(
                '<a href="%s">%s</a>'
                % (
                    url,
                    self.unlisted_text.format(
                        record.unlisted_versions_that_need_human_review
                    ),
                )
            )

        return markupsafe.Markup(''.join(rval))

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_mad_queue(
            admin_reviewer=is_admin_reviewer(request.user)
        ).annotate(
            unlisted_versions_that_need_human_review=Count(
                'versions',
                filter=Q(
                    versions__reviewerflags__needs_human_review_by_mad=True,
                    versions__channel=amo.CHANNEL_UNLISTED,
                ),
            ),
            listed_versions_that_need_human_review=F(
                '_current_version__reviewerflags__needs_human_review_by_mad'
            ),
        )


class ModerationQueueTable:
    title = 'Rating Reviews'
    urlname = 'queue_moderated'
    url = r'^reviews$'
    permission = amo.permissions.RATINGS_MODERATE
    show_count_in_dashboard = False
    view_name = 'queue_moderated'


class ReviewHelper:
    """
    A class that builds enough to render the form back to the user and
    process off to the correct handler.
    """

    def __init__(
        self,
        *,
        addon,
        version=None,
        user=None,
        content_review=False,
        human_review=True,
    ):
        self.handler = None
        self.required = {}
        self.addon = addon
        self.version = version
        self.content_review = content_review
        if human_review and user is None:
            raise RuntimeError(
                'A user should be passed to ReviewHelper when human_review is True'
            )
        elif not human_review:
            user = get_task_user()
        self.human_review = human_review
        self.user = user
        self.set_review_handler()
        self.actions = self.get_actions()

    @property
    def redirect_url(self):
        return self.handler.redirect_url

    def set_data(self, data):
        self.handler.set_data(data)

    def set_review_handler(self):
        """Set the handler property."""
        if self.version and self.version.channel == amo.CHANNEL_UNLISTED:
            self.handler = ReviewUnlisted(
                addon=self.addon,
                version=self.version,
                review_type='unlisted',
                user=self.user,
                human_review=self.human_review,
                content_review=self.content_review,
            )
        elif self.addon.status == amo.STATUS_NOMINATED:
            self.handler = ReviewAddon(
                addon=self.addon,
                version=self.version,
                review_type='nominated',
                user=self.user,
                human_review=self.human_review,
                content_review=self.content_review,
            )
        else:
            self.handler = ReviewFiles(
                addon=self.addon,
                version=self.version,
                review_type='pending',
                user=self.user,
                human_review=self.human_review,
                content_review=self.content_review,
            )

    def get_actions(self):
        actions = OrderedDict()
        # 2 kind of checks are made for the review page.
        # - Base permission checks to access the review page itself, done in
        #   the review() view
        # - A more specific check for each action, done below, restricting
        #   their availability while not affecting whether the user can see
        #   the review page or not.
        version_is_unlisted = (
            self.version and self.version.channel == amo.CHANNEL_UNLISTED
        )
        version_is_listed = self.version and self.version.channel == amo.CHANNEL_LISTED
        promoted_group = self.addon.promoted_group(currently_approved=False)
        is_static_theme = self.addon.type == amo.ADDON_STATICTHEME

        # Default permissions / admin needed values if it's just a regular
        # code review, nothing fancy.
        permission = amo.permissions.ADDONS_REVIEW
        permission_post_review = amo.permissions.ADDONS_REVIEW
        is_admin_needed = is_admin_needed_post_review = False

        # More complex/specific cases.
        if promoted_group == RECOMMENDED:
            permission = amo.permissions.ADDONS_RECOMMENDED_REVIEW
            permission_post_review = permission
        elif version_is_unlisted:
            permission = amo.permissions.ADDONS_REVIEW_UNLISTED
            permission_post_review = permission
        elif promoted_group.admin_review:
            is_admin_needed = is_admin_needed_post_review = True
        elif self.content_review:
            permission = amo.permissions.ADDONS_CONTENT_REVIEW
        elif is_static_theme:
            is_admin_needed = self.addon.needs_admin_theme_review
            permission = amo.permissions.STATIC_THEMES_REVIEW
            permission_post_review = permission

        # In addition, if the latest (or current for post-review) version is
        # pending rejection, an admin is needed.
        if self.version and self.version.pending_rejection:
            is_admin_needed = True
        if self.addon.current_version and self.addon.current_version.pending_rejection:
            is_admin_needed_post_review = True

        # Whatever permission values we set, we override if an admin is needed.
        if is_admin_needed:
            permission = amo.permissions.REVIEWS_ADMIN
        if is_admin_needed_post_review:
            permission_post_review = amo.permissions.REVIEWS_ADMIN

        # Is the current user a reviewer for this kind of add-on ?
        is_reviewer = acl.is_reviewer(self.user, self.addon)

        # Is the current user an appropriate reviewer, not only for this kind
        # of add-on, but also for the state the add-on is in ? (Allows more
        # impactful actions).
        is_appropriate_reviewer = acl.action_allowed_for(self.user, permission)
        is_appropriate_reviewer_post_review = acl.action_allowed_for(
            self.user, permission_post_review
        )
        is_appropriate_admin_reviewer = is_appropriate_reviewer and is_admin_reviewer(
            self.user
        )

        addon_is_not_deleted = self.addon.status != amo.STATUS_DELETED
        addon_is_not_disabled = self.addon.status != amo.STATUS_DISABLED
        addon_is_not_disabled_or_deleted = self.addon.status not in (
            amo.STATUS_DELETED,
            amo.STATUS_DISABLED,
        )
        addon_is_incomplete_and_version_is_unlisted = (
            self.addon.status == amo.STATUS_NULL and version_is_unlisted
        )
        addon_is_reviewable = (
            addon_is_not_disabled_or_deleted and self.addon.status != amo.STATUS_NULL
        ) or addon_is_incomplete_and_version_is_unlisted
        version_is_unreviewed = self.version and self.version.is_unreviewed
        version_was_rejected = bool(
            self.version
            and self.version.file.status == amo.STATUS_DISABLED
            and self.version.human_review_date
        )
        addon_is_valid = self.addon.is_public() or self.addon.is_unreviewed()
        addon_is_valid_and_version_is_listed = addon_is_valid and version_is_listed
        current_or_latest_listed_version_was_auto_approved = version_is_listed and (
            (
                self.addon.current_version
                and self.addon.current_version.was_auto_approved
            )
            or (not self.addon.current_version and self.version.was_auto_approved)
        )
        version_is_blocked = self.version and self.version.is_blocked

        self.unresolved_cinderjob_qs = (
            CinderJob.objects.for_addon(self.addon)
            .unresolved()
            .resolvable_in_reviewer_tools()
            .prefetch_related(
                'abusereport_set',
                'appealed_decisions__cinder_job',
                'appealed_decisions__appeals',
            )
        )
        unresolved_cinder_jobs = list(self.unresolved_cinderjob_qs)
        has_unresolved_abuse_report_jobs = any(
            job for job in unresolved_cinder_jobs if not job.is_appeal
        )
        has_unresolved_appeal_jobs = any(
            job for job in unresolved_cinder_jobs if job.is_appeal
        )

        # Special logic for availability of reject/approve multiple action:
        if version_is_unlisted:
            can_reject_multiple = is_appropriate_reviewer
            can_approve_multiple = is_appropriate_reviewer
        elif self.content_review or promoted_group.listed_pre_review or is_static_theme:
            can_reject_multiple = (
                addon_is_valid_and_version_is_listed and is_appropriate_reviewer
            )
            can_approve_multiple = False
        else:
            # When doing a code review, this action is also available to
            # users with Addons:PostReview even if the current version hasn't
            # been auto-approved, provided that the add-on isn't marked as
            # needing admin review.
            can_reject_multiple = addon_is_valid_and_version_is_listed and (
                is_appropriate_reviewer
                or is_appropriate_reviewer_post_review
                or not self.human_review
            )
            can_approve_multiple = False

        # Definitions for all actions.
        actions['public'] = {
            'method': self.handler.approve_latest_version,
            'minimal': False,
            'details': (
                'This will approve, sign, and publish this '
                'version. The comments will be sent to the '
                'developer.'
            ),
            'label': 'Approve',
            'available': (
                not self.content_review
                and addon_is_reviewable
                and version_is_unreviewed
                and (is_appropriate_reviewer or not self.human_review)
                and not version_is_blocked
            ),
            'allows_reasons': not is_static_theme,
            'resolves_abuse_reports': True,
            'requires_reasons': False,
            'boilerplate_text': 'Thank you for your contribution.',
            'can_attach': True,
        }
        actions['reject'] = {
            'method': self.handler.reject_latest_version,
            'label': 'Reject',
            'details': (
                'This will reject this version and remove it '
                'from the queue. The comments will be sent '
                'to the developer.'
            ),
            'minimal': False,
            'available': (
                not self.content_review
                # We specifically don't let the individual reject action be
                # available for unlisted review. `reject_latest_version` isn't
                # currently implemented for unlisted.
                and addon_is_valid_and_version_is_listed
                and version_is_unreviewed
                and is_appropriate_reviewer
            ),
            'allows_reasons': True,
            'resolves_abuse_reports': True,
            'requires_reasons': not is_static_theme,
        }
        actions['approve_content'] = {
            'method': self.handler.approve_content,
            'label': 'Approve Content',
            'details': (
                'This records your approbation of the '
                'content of the latest public version, '
                'without notifying the developer.'
            ),
            'minimal': False,
            'comments': False,
            'available': (
                self.content_review
                and addon_is_valid_and_version_is_listed
                and is_appropriate_reviewer
            ),
        }
        actions['confirm_auto_approved'] = {
            'method': self.handler.confirm_auto_approved,
            'label': 'Confirm Approval',
            'details': (
                'The latest public version of this add-on was '
                'automatically approved. This records your '
                'confirmation of the approval of that version, '
                'without notifying the developer.'
            ),
            'minimal': True,
            'comments': False,
            'available': (
                not self.content_review
                and current_or_latest_listed_version_was_auto_approved
                and is_appropriate_reviewer_post_review
            ),
            'resolves_abuse_reports': True,
        }
        actions['approve_multiple_versions'] = {
            'method': self.handler.approve_multiple_versions,
            'label': 'Approve Multiple Versions',
            'minimal': True,
            'multiple_versions': True,
            'details': (
                'This will approve the selected versions. '
                'The comments will be sent to the developer.'
            ),
            'available': (can_approve_multiple),
            'allows_reasons': not is_static_theme,
            'requires_reasons': False,
            'resolves_abuse_reports': True,
        }
        actions['reject_multiple_versions'] = {
            'method': self.handler.reject_multiple_versions,
            'label': 'Reject Multiple Versions',
            'minimal': True,
            'delayable': True,
            'multiple_versions': True,
            'details': (
                'This will reject the selected versions. '
                'The comments will be sent to the developer.'
            ),
            'available': (can_reject_multiple),
            'allows_reasons': True,
            'resolves_abuse_reports': True,
            'requires_reasons': not is_static_theme,
        }
        actions['unreject_latest_version'] = {
            'method': self.handler.unreject_latest_version,
            'label': 'Un-reject',
            'minimal': True,
            'details': (
                'This will un-reject the latest version without notifying the '
                'developer.'
            ),
            'comments': False,
            'available': (
                not version_is_unlisted
                and addon_is_not_disabled_or_deleted
                and version_was_rejected
                and is_appropriate_admin_reviewer
            ),
        }
        actions['unreject_multiple_versions'] = {
            'method': self.handler.unreject_multiple_versions,
            'label': 'Un-reject Versions',
            'minimal': True,
            'multiple_versions': True,
            'details': (
                'This will un-reject the selected versions without notifying the '
                'developer.'
            ),
            'comments': False,
            'available': (
                version_is_unlisted
                and addon_is_not_disabled_or_deleted
                and is_appropriate_admin_reviewer
            ),
        }
        actions['block_multiple_versions'] = {
            'method': self.handler.block_multiple_versions,
            'label': 'Block Multiple Versions',
            'minimal': True,
            'multiple_versions': True,
            'comments': False,
            'details': (
                'This will disable the selected approved '
                'versions silently, and open up the block creation '
                'admin page.'
            ),
            'available': (
                not is_static_theme and version_is_unlisted and is_appropriate_reviewer
            ),
        }
        actions['confirm_multiple_versions'] = {
            'method': self.handler.confirm_multiple_versions,
            'label': 'Confirm Multiple Versions',
            'minimal': True,
            'multiple_versions': True,
            'details': (
                'This will confirm approval of the selected '
                'versions without notifying the developer.'
            ),
            'comments': False,
            'available': (
                not is_static_theme and version_is_unlisted and is_appropriate_reviewer
            ),
            'resolves_abuse_reports': True,
        }
        actions['clear_pending_rejection_multiple_versions'] = {
            'method': self.handler.clear_pending_rejection_multiple_versions,
            'label': 'Clear pending rejection',
            'details': (
                'Clear pending rejection from selected versions, but '
                "otherwise don't change the version(s) or add-on statuses."
            ),
            'multiple_versions': True,
            'minimal': True,
            'comments': False,
            'available': is_appropriate_admin_reviewer,
        }
        actions['clear_needs_human_review_multiple_versions'] = {
            'method': self.handler.clear_needs_human_review_multiple_versions,
            'label': 'Clear Needs Human Review',
            'details': (
                'Clear needs human review flag from selected versions, but '
                "otherwise don't change the version(s) or add-on statuses."
            ),
            'multiple_versions': True,
            'minimal': True,
            'comments': False,
            'available': is_appropriate_admin_reviewer,
        }
        actions['set_needs_human_review_multiple_versions'] = {
            'method': self.handler.set_needs_human_review_multiple_versions,
            'label': 'Set Needs Human Review',
            'details': (
                'Set needs human review flag from selected versions, but '
                "otherwise don't change the version(s) or add-on statuses."
            ),
            'multiple_versions': True,
            'minimal': True,
            'available': addon_is_not_disabled and is_appropriate_reviewer,
        }
        actions['reply'] = {
            'method': self.handler.reviewer_reply,
            'label': 'Reviewer reply',
            'details': (
                'This will send a message to the developer, attached to the '
                'selected version(s). You will be notified when they reply.'
            ),
            'multiple_versions': True,
            'minimal': True,
            'available': (
                self.version is not None
                and is_reviewer
                and (not promoted_group.admin_review or is_appropriate_reviewer)
            ),
            'allows_reasons': not is_static_theme,
            'requires_reasons': False,
        }
        actions['request_admin_review'] = {
            'method': self.handler.request_admin_review,
            'label': 'Request review from admin',
            'details': (
                'If you have concerns about this add-on that '
                'an admin reviewer should look into, enter '
                'your comments in the area below. They will '
                'not be sent to the developer.'
            ),
            'minimal': True,
            'available': (self.version is not None and is_reviewer and is_static_theme),
        }
        actions['clear_admin_review'] = {
            'method': self.handler.clear_admin_review,
            'label': 'Clear admin review',
            'details': ('Clear needs admin review flag on the add-on.'),
            'minimal': True,
            'comments': False,
            'available': is_appropriate_admin_reviewer and is_static_theme,
        }
        actions['enable_addon'] = {
            'method': self.handler.enable_addon,
            'label': 'Force enable',
            'details': (
                'This will force enable this add-on, and any versions previously '
                'disabled with Force Disable. '
                'The comments will be sent to the developer.'
            ),
            'minimal': True,
            'available': (
                addon_is_not_deleted
                and not addon_is_not_disabled
                and is_appropriate_admin_reviewer
            ),
            'resolves_abuse_reports': True,
            'can_attach': False,
        }
        actions['disable_addon'] = {
            'method': self.handler.disable_addon,
            'label': 'Force disable',
            'details': (
                'This will force disable this add-on, and all its versions. '
                'The comments will be sent to the developer.'
            ),
            'minimal': False,
            'available': (
                addon_is_not_disabled_or_deleted and is_appropriate_admin_reviewer
            ),
            'allows_reasons': True,
            'requires_reasons': not is_static_theme,
            'resolves_abuse_reports': True,
            'can_attach': False,
        }
        actions['resolve_reports_job'] = {
            'method': self.handler.resolve_reports_job,
            'label': 'Resolve Reports',
            'details': (
                'Allows abuse report jobs to be resovled without an action on the '
                'add-on or versions.'
            ),
            'minimal': True,
            'available': is_reviewer and has_unresolved_abuse_report_jobs,
            'comments': False,
            'resolves_abuse_reports': True,
            'allows_policies': True,
        }
        actions['resolve_appeal_job'] = {
            'method': self.handler.resolve_appeal_job,
            'label': 'Resolve Appeals',
            'details': (
                'Allows abuse report jobs to be resovled without an action on the '
                'add-on or versions.'
            ),
            'minimal': True,
            'available': is_reviewer and has_unresolved_appeal_jobs,
            'comments': True,
            'resolves_abuse_reports': True,
        }
        actions['comment'] = {
            'method': self.handler.process_comment,
            'label': 'Comment',
            'details': (
                "Make a comment on this version. The developer won't be able to see "
                'this.'
            ),
            'minimal': True,
            'available': is_reviewer,
        }
        return OrderedDict(
            ((key, action) for key, action in actions.items() if action['available'])
        )

    def process(self):
        if not (action := self.actions.get(self.handler.data.get('action'))):
            raise NotImplementedError
        # Clear comments in data before processing if the action isn't supposed
        # to have any, because the reviewer might have submitted some by
        # accident after switching between tabs, and the logging methods will
        # automatically include them if some are present.
        if not action.get('comments', True):
            self.handler.data['comments'] = ''
        self.handler.review_action = action
        return action['method']()


class ReviewBase:
    review_action = None  # set via ReviewHelper.process

    def __init__(
        self,
        *,
        addon,
        version,
        user,
        review_type,
        content_review=False,
        human_review=True,
    ):
        self.user = user
        self.human_review = human_review
        self.addon = addon
        self.version = version
        self.review_type = (
            'theme_%s' if addon.type == amo.ADDON_STATICTHEME else 'extension_%s'
        ) % review_type
        self.file = (
            self.version.file
            if self.version and self.version.file.status == amo.STATUS_AWAITING_REVIEW
            else None
        )
        self.content_review = content_review
        self.redirect_url = None

    def set_addon(self):
        """Alter addon, set human_review_date timestamp on version being reviewed."""
        self.addon.update_status()
        self.set_human_review_date()

    def set_human_review_date(self, version=None):
        version = version or self.version
        if self.human_review and not version.human_review_date:
            version.update(human_review_date=datetime.now())

    def set_data(self, data):
        self.data = data

    def set_file(self, status, file):
        """Change the file to be the new status."""
        file.datestatuschanged = datetime.now()
        if status == amo.STATUS_APPROVED:
            file.approval_date = datetime.now()
        file.status = status
        if status == amo.STATUS_DISABLED:
            file.original_status = amo.STATUS_NULL
        file.save()

    def set_promoted(self, versions=None):
        group = self.addon.promoted_group(currently_approved=False)
        if versions is None:
            versions = [self.version]
        elif not versions:
            return
        channel = versions[0].channel
        if group and (
            (channel == amo.CHANNEL_LISTED and group.listed_pre_review)
            or (channel == amo.CHANNEL_UNLISTED and group.unlisted_pre_review)
        ):
            # These addons shouldn't be be attempted for auto approval anyway,
            # but double check that the cron job isn't trying to approve it.
            assert not self.user.id == settings.TASK_USER_ID
            for version in versions:
                self.addon.promotedaddon.approve_for_version(version)

    def notify_decision(self):
        if cinder_jobs := self.data.get('cinder_jobs_to_resolve', ()):
            # with appeals and escalations there could be multiple jobs
            for cinder_job in cinder_jobs:
                resolve_job_in_cinder.delay(
                    cinder_job_id=cinder_job.id, log_entry_id=self.log_entry.id
                )
        else:
            notify_addon_decision_to_cinder.delay(
                log_entry_id=self.log_entry.id, addon_id=self.addon.id
            )

    def clear_all_needs_human_review_flags_in_channel(self, mad_too=True):
        """Clear needs_human_review flags on all versions in the same channel.

        Doesn't clear abuse or appeal related flags.
        To be called when approving a listed version: For listed, the version
        reviewers are approving is always the latest listed one, and then users
        are supposed to automatically get the update to that version, so we
        don't need to care about older ones anymore.
        """
        # Do a mass UPDATE. The NeedsHumanReview coming from
        # abuse/appeal/escalations are only cleared in CinderJob.resolve_job()
        # if the reviewer has selected to resolve all jobs of that type though.
        NeedsHumanReview.objects.filter(
            version__addon=self.addon,
            version__channel=self.version.channel,
            is_active=True,
        ).exclude(
            reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values
        ).update(is_active=False)
        if mad_too:
            # Another one for the needs_human_review_by_mad flag.
            VersionReviewerFlags.objects.filter(
                version__addon=self.addon,
                version__channel=self.version.channel,
            ).update(needs_human_review_by_mad=False)
        # Trigger a check of all due dates on the add-on since we mass-updated
        # versions.
        self.addon.update_all_due_dates()

    def clear_specific_needs_human_review_flags(
        self, version, *, abuse_appeal_too=False
    ):
        """Clear needs_human_review flags on a specific version."""
        qs = version.needshumanreview_set.filter(is_active=True)
        if not abuse_appeal_too:
            qs = qs.exclude(
                reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values
            )
        qs.update(is_active=False)
        if version.needs_human_review_by_mad:
            version.reviewerflags.update(needs_human_review_by_mad=False)
        # Because the updating of needs human review was made with a queryset
        # the post_save signal was not triggered so let's recheck the due date
        # explicitly.
        version.reset_due_date()

    def get_cinder_actions_from_policies(self, policies):
        return list(
            {
                DECISION_ACTIONS.for_value(policy.default_cinder_action)
                for policy in policies
                if getattr(policy, 'default_cinder_action', None)
            }
        )

    def log_action(
        self,
        action,
        *,
        version=None,
        versions=None,
        file=None,
        timestamp=None,
        user=None,
        extra_details=None,
        policies=None,
        cinder_action=None,
    ):
        reasons = (
            self.data.get('reasons', [])
            if self.review_action and self.review_action.get('allows_reasons')
            else []
        )
        if policies is None:
            policies = [
                reason.cinder_policy
                for reason in reasons
                if getattr(reason, 'cinder_policy', None)
            ]
            if self.review_action and self.review_action.get('allows_policies'):
                policies.extend(self.data.get('cinder_policies', []))

        cinder_action = cinder_action or getattr(action, 'cinder_action', None)
        if not cinder_action and policies:
            cinder_action = (
                # If there isn't a cinder_action from the activity action already, get
                # it from the policy. There should only be one in the list as form
                # validation raises for multiple cinder actions.
                (actions := self.get_cinder_actions_from_policies(policies))
                and actions[0]
            )

        details = {
            'comments': self.data.get('comments', ''),
            'reviewtype': self.review_type.split('_')[1],
            'human_review': self.human_review,
            'cinder_action': cinder_action and cinder_action.constant,
            **(extra_details or {}),
        }
        if version is None and self.version:
            version = self.version

        if file is not None:
            details['files'] = [file.id]
        elif self.file:
            details['files'] = [self.file.id]

        if version is not None:
            details['version'] = version.version
            args = (self.addon, version)
        elif versions is not None:
            details['versions'] = [v.version for v in versions]
            details['files'] = [v.file.id for v in versions]
            args = (self.addon, *versions)
        else:
            args = (self.addon,)
        if timestamp is None:
            timestamp = datetime.now()

        args = (*args, *reasons, *policies)
        kwargs = {'user': user or self.user, 'created': timestamp, 'details': details}
        self.log_entry = ActivityLog.objects.create(action, *args, **kwargs)

        attachment = None
        if self.data.get('attachment_file'):
            attachment = self.data.get('attachment_file')
        elif self.data.get('attachment_input'):
            # The name will be overridden later by attachment_upload_path.
            attachment = ContentFile(
                self.data['attachment_input'], name='attachment.txt'
            )
        if attachment is not None:
            AttachmentLog.objects.create(activity_log=self.log_entry, file=attachment)

    def reviewer_reply(self):
        # Default to reviewer reply action.
        action = amo.LOG.REVIEWER_REPLY_VERSION
        self.version = None
        self.file = None
        versions = self.data['versions']
        log.info(
            'Sending reviewer reply for %s versions %s to authors and other'
            'recipients' % (self.addon, map(str, versions))
        )
        self.log_action(action, versions=versions)
        for version in versions:
            notify_about_activity_log(
                self.addon, version, self.log_entry, perm_setting='individual_contact'
            )

    def sign_file(self):
        assert not (self.version and self.version.is_blocked)
        if self.file:
            if self.file.is_experiment:
                ActivityLog.objects.create(
                    amo.LOG.EXPERIMENT_SIGNED, self.file, user=self.user
                )
            sign_file(self.file)

    def process_comment(self):
        self.log_action(amo.LOG.COMMENT_VERSION)

    def resolve_reports_job(self):
        if self.data.get('cinder_jobs_to_resolve', ()):
            self.log_action(amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION)
            self.notify_decision()  # notify cinder

    def resolve_appeal_job(self):
        # It's possible to have multiple appeal jobs, so handle them seperately.
        for job in self.data.get('cinder_jobs_to_resolve', ()):
            # collect all the policies we made decisions under
            previous_policies = CinderPolicy.objects.filter(
                cinderdecision__appeal_job=job
            ).distinct()
            # we just need a single action for this appeal
            # - use min() to favor AMO_DISABLE_ADDON over AMO_REJECT_VERSION_ADDON
            previous_action_id = min(
                decision.action for decision in job.appealed_decisions.all()
            )
            self.log_action(
                amo.LOG.DENY_APPEAL_JOB,
                policies=list(previous_policies),
                cinder_action=DECISION_ACTIONS.for_value(previous_action_id),
            )
            # notify cinder
            resolve_job_in_cinder.delay(
                cinder_job_id=job.id, log_entry_id=self.log_entry.id
            )

    def approve_latest_version(self):
        """Approve the add-on latest version (potentially setting the add-on to
        approved if it was awaiting its first review)."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.CHANNEL_LISTED

        # Safeguard to make sure this action is not used for content review
        # (it should use confirm_auto_approved instead).
        assert not self.content_review

        # Sign addon.
        self.sign_file()

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_file(amo.STATUS_APPROVED, self.file)
        self.set_promoted()
        if self.set_addon_status:
            self.set_addon()

        if self.human_review:
            # No need for a human review anymore in this channel.
            self.clear_all_needs_human_review_flags_in_channel()

            # Clear pending rejection since we approved that version.
            VersionReviewerFlags.objects.filter(version=self.version).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )

            # An approval took place so we can reset this.
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon,
                defaults={'auto_approval_disabled_until_next_approval': False},
            )

            # The counter can be incremented.
            AddonApprovalsCounter.increment_for_addon(addon=self.addon)
            self.set_human_review_date()
        else:
            # Automatic approval, reset the counter.
            AddonApprovalsCounter.reset_for_addon(addon=self.addon)

        self.log_action(amo.LOG.APPROVE_VERSION)
        if self.human_review or self.addon.type != amo.ADDON_LPAPP:
            # Don't notify decisions (to cinder or owners) for auto-approved langpacks
            log.info('Sending email for %s' % (self.addon))
            self.notify_decision()
        self.log_public_message()

    def reject_latest_version(self):
        """Reject the add-on latest version (potentially setting the add-on
        back to incomplete if it was awaiting its first review)."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.CHANNEL_LISTED

        # Safeguard to make sure this action is not used for content review
        # (it should use reject_multiple_versions instead).
        assert not self.content_review

        self.set_file(amo.STATUS_DISABLED, self.file)
        if self.set_addon_status:
            self.set_addon()

        if self.human_review:
            # Clear needs human review flags, but only on the latest version:
            # it's the only version we can be certain that the reviewer looked
            # at.
            self.clear_specific_needs_human_review_flags(self.version)
            self.set_human_review_date()

        self.log_action(amo.LOG.REJECT_VERSION)
        log.info('Sending email for %s' % (self.addon))
        # This call has to happen after log_action - we need self.log_entry
        self.notify_decision()
        self.log_sandbox_message()

    def request_admin_review(self):
        """Mark an add-on as needing admin theme review."""
        if self.addon.type == amo.ADDON_STATICTHEME:
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon, defaults={'needs_admin_theme_review': True}
            )
            self.log_action(amo.LOG.REQUEST_ADMIN_REVIEW_THEME)
            log.info(f'{amo.LOG.REQUEST_ADMIN_REVIEW_THEME.short} for {self.addon}')

    def clear_admin_review(self):
        if self.addon.type == amo.ADDON_STATICTHEME:
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon, defaults={'needs_admin_theme_review': False}
            )
            self.log_action(amo.LOG.CLEAR_ADMIN_REVIEW_THEME)
            log.info(f'{amo.LOG.CLEAR_ADMIN_REVIEW_THEME.short} for {self.addon}')

    def approve_content(self):
        """Approve content of an add-on."""
        channel = self.version.channel
        version = self.addon.current_version

        # Content review only action.
        assert self.content_review

        # Doesn't make sense for unlisted versions.
        assert channel == amo.CHANNEL_LISTED

        # When doing a content review, don't increment the approvals counter,
        # just record the date of the content approval and log it.
        AddonApprovalsCounter.approve_content_for_addon(addon=self.addon)
        self.log_action(amo.LOG.APPROVE_CONTENT, version=version)

    def confirm_auto_approved(self):
        """Confirm an auto-approval decision."""

        channel = self.version.channel
        if channel == amo.CHANNEL_LISTED:
            # When confirming an approval in listed channel, the version we
            # care about is generally the current_version, because this allows
            # reviewers to confirm approval of a public add-on even when their
            # latest version is disabled.
            # However, if there is no current_version, because the entire
            # add-on is deleted or invisible for instance, we still want to
            # allow confirming approval, so we use self.version in that case.
            version = self.addon.current_version or self.version
        else:
            # For unlisted, we just use self.version.
            version = self.version

        self.log_action(amo.LOG.CONFIRM_AUTO_APPROVED, version=version)

        if self.human_review:
            self.set_promoted()
            # Mark the approval as confirmed (handle DoesNotExist, it may have
            # been auto-approved before we unified workflow for unlisted and
            # listed).
            try:
                version.autoapprovalsummary.update(confirmed=True)
            except AutoApprovalSummary.DoesNotExist:
                pass

            if channel == amo.CHANNEL_LISTED:
                # Clear needs human review flags on past versions in channel.
                self.clear_all_needs_human_review_flags_in_channel()
                AddonApprovalsCounter.increment_for_addon(addon=self.addon)
            else:
                # For unlisted versions, only drop the needs_human_review flag
                # on the latest version.
                self.clear_specific_needs_human_review_flags(self.version)

            # Clear the "pending_rejection" flag for all versions (Note that
            # the action should only be accessible to admins if the current
            # version is pending rejection).
            VersionReviewerFlags.objects.filter(
                version__addon=self.addon,
                version__channel=channel,
            ).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )
            self.set_human_review_date(version)
            self.notify_decision()

    def reject_multiple_versions(self):
        """Reject a list of versions.
        Note: this is used in blocklist.utils.disable_addon_for_block for both
        listed and unlisted versions (human_review=False)."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        channel = self.version.channel if self.version else None
        self.version = None
        self.file = None
        now = datetime.now()
        if self.data.get('delayed_rejection'):
            pending_rejection_deadline = now + timedelta(
                days=int(self.data['delayed_rejection_days'])
            )
        else:
            pending_rejection_deadline = None
        if pending_rejection_deadline:
            action_id = (
                amo.LOG.REJECT_CONTENT_DELAYED
                if self.content_review
                else amo.LOG.REJECT_VERSION_DELAYED
            )
            log.info(
                'Marking %s versions %s for delayed rejection'
                % (self.addon, ', '.join(str(v.pk) for v in self.data['versions']))
            )
        else:
            action_id = (
                amo.LOG.REJECT_CONTENT
                if self.content_review
                else amo.LOG.REJECT_VERSION
            )
            log.info(
                'Making %s versions %s disabled'
                % (self.addon, ', '.join(str(v.pk) for v in self.data['versions']))
            )
        # For a human review we record a single action, but for automated
        # stuff, we need to split by type (content review or not) and by
        # original user to match the original user(s) and action(s).
        actions_to_record = defaultdict(lambda: defaultdict(list))
        for version in self.data['versions']:
            file = version.file
            if not pending_rejection_deadline:
                self.set_file(amo.STATUS_DISABLED, file)

            if (
                not self.human_review
                and (flags := getattr(version, 'reviewerflags', None))
                and flags.pending_rejection
            ):
                action_id = (
                    amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED
                    if flags.pending_content_rejection
                    else amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED
                )
            if self.human_review:
                # Clear needs human review flags on rejected versions, we
                # consider that the reviewer looked at them before rejecting.
                self.clear_specific_needs_human_review_flags(version)
                # (Re)set pending_rejection. Could be reset to None if doing an
                # immediate rejection.
                VersionReviewerFlags.objects.update_or_create(
                    version=version,
                    defaults={
                        'pending_rejection': pending_rejection_deadline,
                        'pending_rejection_by': self.user
                        if pending_rejection_deadline
                        else None,
                        'pending_content_rejection': self.content_review
                        if pending_rejection_deadline
                        else None,
                    },
                )
                self.set_human_review_date(version)
                actions_to_record[action_id][self.user].append(version)
            else:
                actions_to_record[action_id][version.pending_rejection_by].append(
                    version
                )

        extra_details = {}
        for key in [
            'delayed_rejection_days',
            'is_addon_being_blocked',
            'is_addon_being_disabled',
        ]:
            if key in self.data:
                extra_details[key] = self.data[key]

        for action_id, user_and_versions in actions_to_record.items():
            for user, versions in user_and_versions.items():
                self.log_action(
                    action_id,
                    versions=versions,
                    timestamp=now,
                    user=user,
                    extra_details=extra_details,
                )

        addonreviewerflags = {}
        # A human rejection (delayed or not) implies the next version in the
        # same channel should be manually reviewed.
        if self.human_review:
            auto_approval_disabled_until_next_approval_flag = (
                'auto_approval_disabled_until_next_approval'
                if channel == amo.CHANNEL_LISTED
                else 'auto_approval_disabled_until_next_approval_unlisted'
            )
            addonreviewerflags[auto_approval_disabled_until_next_approval_flag] = True
        if pending_rejection_deadline:
            # Developers should be notified again once the deadline is close.
            addonreviewerflags['notified_about_expiring_delayed_rejections'] = False
        else:
            # An immediate rejection might require the add-on status to change.
            self.addon.update_status()
        if addonreviewerflags:
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon,
                defaults=addonreviewerflags,
            )

        if actions_to_record:
            # if we didn't record any actions we didn't do anything so nothing to notify
            log.info('Sending email for %s' % (self.addon))
            self.notify_decision()

    def unreject_latest_version(self):
        """Un-reject the latest version."""
        # we're only supporting non-automated reviews right now:
        assert self.human_review

        log.info(
            'Making %s versions %s awaiting review (not disabled)'
            % (self.addon, self.version.pk)
        )

        self.set_file(amo.STATUS_AWAITING_REVIEW, self.version.file)
        self.log_action(amo.LOG.UNREJECT_VERSION)
        self.addon.update_status(self.user)

    def confirm_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def approve_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def block_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def unreject_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def clear_needs_human_review_multiple_versions(self):
        """Clear human review on selected versions."""
        self.file = None
        self.version = None
        for version in self.data['versions']:
            # Do it one by one to trigger the post_save().
            self.clear_specific_needs_human_review_flags(version)
        # Record a single activity log.
        self.log_action(
            amo.LOG.CLEAR_NEEDS_HUMAN_REVIEW, versions=self.data['versions']
        )

    def set_needs_human_review_multiple_versions(self):
        """Record human review flag on selected versions."""
        self.file = None
        self.version = None
        for version in self.data['versions']:
            # Do it one by one to trigger the post_save(), but avoid the
            # individual activity logs: we'll record a single one ourselves.
            NeedsHumanReview(
                version=version,
                reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER,
            ).save(_no_automatic_activity_log=True)
        # Record a single activity log.
        self.log_action(
            amo.LOG.NEEDS_HUMAN_REVIEW,
            versions=self.data['versions'],
        )

    def clear_pending_rejection_multiple_versions(self):
        """Clear pending rejection on selected versions."""
        self.file = None
        self.version = None
        for version in self.data['versions']:
            # Do it one by one to trigger the post_save().
            if version.pending_rejection:
                version.reviewerflags.update(
                    pending_rejection=None,
                    pending_rejection_by=None,
                    pending_content_rejection=None,
                )
        # Record a single activity log.
        self.log_action(amo.LOG.CLEAR_PENDING_REJECTION, versions=self.data['versions'])

    def enable_addon(self):
        """Force enable the add-on."""
        self.version = None
        self.addon.force_enable(skip_activity_log=True)
        self.log_action(amo.LOG.FORCE_ENABLE)
        log.info('Sending email for %s' % (self.addon))
        self.notify_decision()

    def disable_addon(self):
        """Force disable the add-on and all versions."""
        self.addon.force_disable(skip_activity_log=True)
        self.log_action(amo.LOG.FORCE_DISABLE)
        log.info('Sending email for %s' % (self.addon))
        self.notify_decision()


class ReviewAddon(ReviewBase):
    set_addon_status = True

    def log_public_message(self):
        log.info('Making %s public' % (self.addon))

    def log_sandbox_message(self):
        log.info('Making %s disabled' % (self.addon))


class ReviewFiles(ReviewBase):
    set_addon_status = False

    def log_public_message(self):
        log.info(
            'Making %s files %s public'
            % (self.addon, self.file.file.name if self.file else '')
        )

    def log_sandbox_message(self):
        log.info(
            'Making %s files %s disabled'
            % (self.addon, self.file.file.name if self.file else '')
        )


class ReviewUnlisted(ReviewBase):
    def approve_latest_version(self):
        """Set an unlisted addon version files to public."""
        assert self.version.channel == amo.CHANNEL_UNLISTED

        # Sign addon.
        self.sign_file()
        if self.file:
            ActivityLog.objects.create(
                amo.LOG.UNLISTED_SIGNED, self.file, user=self.user
            )

        self.set_file(amo.STATUS_APPROVED, self.file)

        self.log_action(amo.LOG.APPROVE_VERSION)

        if self.human_review:
            self.set_promoted()
            self.clear_specific_needs_human_review_flags(self.version)

            # Clear pending rejection since we approved that version.
            VersionReviewerFlags.objects.filter(version=self.version).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )

            # An approval took place so we can reset this.
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon,
                defaults={'auto_approval_disabled_until_next_approval_unlisted': False},
            )
            self.set_human_review_date()
        elif (
            not self.version.needshumanreview_set.filter(is_active=True)
            and (delay := self.addon.auto_approval_delayed_until_unlisted)
            and delay < datetime.now()
        ):
            # if we're auto-approving because its past the approval delay, flag it.
            NeedsHumanReview.objects.create(
                version=self.version,
                reason=NeedsHumanReview.REASONS.AUTO_APPROVED_PAST_APPROVAL_DELAY,
            )
        log.info(
            'Making %s files %s public'
            % (self.addon, self.file.file.name if self.file else '')
        )
        log.info('Sending email for %s' % (self.addon))
        self.notify_decision()

    def block_multiple_versions(self):
        versions = self.data['versions']
        params = '?' + urlencode((('v', v.id) for v in versions), doseq=True)
        self.redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.pk,)) + params
        )

    def confirm_multiple_versions(self):
        """Confirm approval on a list of versions."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None so that the action is
        # recorded against the specific versions we are confirming approval of.
        self.version = None
        self.file = None

        timestamp = datetime.now()
        for version in self.data['versions']:
            if self.human_review:
                # Mark summary as confirmed if it exists.
                try:
                    version.autoapprovalsummary.update(confirmed=True)
                except AutoApprovalSummary.DoesNotExist:
                    pass
                # Clear needs_human_review on rejected versions, we consider
                # that the reviewer looked at all versions they are approving.
                self.clear_specific_needs_human_review_flags(version)
                self.set_human_review_date(version)

        self.log_action(
            amo.LOG.CONFIRM_AUTO_APPROVED,
            versions=self.data['versions'],
            timestamp=timestamp,
        )
        self.notify_decision()

    def approve_multiple_versions(self):
        """Set multiple unlisted add-on versions files to public."""
        assert self.version.channel == amo.CHANNEL_UNLISTED
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None so that the action is
        # recorded against the specific versions we are approving.
        self.version = None
        self.file = None

        if not self.data['versions']:
            return

        timestamp = datetime.now()
        for version in self.data['versions']:
            # Sign addon.
            assert not version.is_blocked
            if version.file.status == amo.STATUS_AWAITING_REVIEW:
                sign_file(version.file)
            ActivityLog.objects.create(
                amo.LOG.UNLISTED_SIGNED, version.file, user=self.user
            )
            self.set_file(amo.STATUS_APPROVED, version.file)
            if self.human_review:
                self.clear_specific_needs_human_review_flags(version)
            log.info('Making %s files %s public' % (self.addon, version.file.file.name))

        self.log_action(
            amo.LOG.APPROVE_VERSION, versions=self.data['versions'], timestamp=timestamp
        )

        if self.human_review:
            self.set_promoted(versions=self.data['versions'])
            # An approval took place so we can reset this.
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon,
                defaults={'auto_approval_disabled_until_next_approval_unlisted': False},
            )
            log.info('Sending email(s) for %s' % (self.addon))
            self.notify_decision()

    def unreject_multiple_versions(self):
        """Un-reject a list of versions."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        self.version = None
        self.file = None
        # we're only supporting non-automated reviews right now:
        assert self.human_review

        log.info(
            'Making %s versions %s awaiting review (not disabled)'
            % (self.addon, ', '.join(str(v.pk) for v in self.data['versions']))
        )

        for version in self.data['versions']:
            self.set_file(amo.STATUS_AWAITING_REVIEW, version.file)

        self.log_action(
            amo.LOG.UNREJECT_VERSION,
            versions=self.data['versions'],
            user=self.user,
        )

        if self.data['versions']:
            # if these are listed versions then the addon status may need updating
            self.addon.update_status(self.user)
