import random
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import Count, F, Q
from django.template import loader
from django.urls import reverse
from django.utils import translation

import django_tables2 as tables
import markupsafe

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.activity.utils import notify_about_activity_log, send_activity_mail
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import to_language
from olympia.constants.promoted import RECOMMENDED
from olympia.lib.crypto.signing import sign_file
from olympia.reviewers.models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewerSubscription,
    get_flags,
)
from olympia.reviewers.templatetags.jinja_helpers import format_score
from olympia.users.utils import get_task_user
from olympia.versions.models import VersionReviewerFlags


log = olympia.core.logger.getLogger('z.mailer')


def is_admin_reviewer(user):
    return acl.action_allowed_for(user, amo.permissions.REVIEWS_ADMIN)


class AddonQueueTable(tables.Table):
    addon_name = tables.Column(verbose_name='Add-on', accessor='name', orderable=False)
    # Override empty_values for flags so that they can be displayed even if the
    # model does not have a flags attribute.
    flags = tables.Column(verbose_name='Flags', empty_values=(), orderable=False)
    last_human_review = tables.DateTimeColumn(
        verbose_name='Last Review',
        accessor='addonapprovalscounter__last_human_review',
    )
    code_weight = tables.Column(
        verbose_name='Code Weight',
        accessor='_current_version__autoapprovalsummary__code_weight',
    )
    metadata_weight = tables.Column(
        verbose_name='Metadata Weight',
        accessor='_current_version__autoapprovalsummary__metadata_weight',
    )
    weight = tables.Column(
        verbose_name='Total Weight',
        accessor='_current_version__autoapprovalsummary__weight',
    )
    score = tables.Column(
        verbose_name='Maliciousness Score',
        accessor='_current_version__autoapprovalsummary__score',
    )
    show_count_in_dashboard = True
    view_name = 'queue'

    class Meta:
        fields = (
            'addon_name',
            'flags',
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
            'score',
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
        return markupsafe.Markup(
            '<a href="%s">%s <em>%s</em></a>'
            % (
                url,
                markupsafe.escape(record.name),
                markupsafe.escape(self.get_version(record).version),
            )
        )

    def render_last_human_review(self, value):
        return naturaltime(value) if value else ''

    def render_weight(self, *, record, value):
        return markupsafe.Markup(
            '<span title="%s">%d</span>'
            % (
                '\n'.join(
                    self.get_version(
                        record
                    ).autoapprovalsummary.get_pretty_weight_info()
                ),
                value,
            )
        )

    def render_score(self, value):
        return format_score(value)

    render_last_content_review = render_last_human_review


class PendingManualApprovalQueueTable(AddonQueueTable):
    addon_type = tables.Column(verbose_name='Type', accessor='type', orderable=False)
    due_date = tables.Column(verbose_name='Due Date', accessor='first_version_due_date')
    score = tables.Column(
        verbose_name='Maliciousness Score',
        accessor='first_pending_version__autoapprovalsummary__score',
    )
    title = '🛠️ Manual Review'
    urlname = 'queue_extension'
    url = r'^extension$'
    permission = amo.permissions.ADDONS_REVIEW

    class Meta:
        fields = ('addon_name', 'addon_type', 'due_date', 'flags', 'score')
        exclude = (
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
        )

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


class NewThemesQueueTable(PendingManualApprovalQueueTable):
    title = '🎨 New'
    urlname = 'queue_theme_nominated'
    url = r'^theme_new$'
    permission = amo.permissions.STATIC_THEMES_REVIEW

    class Meta(AddonQueueTable.Meta):
        exclude = (
            'score',
            'addon_type',
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
        )

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_queryset_for_pending_queues(
            admin_reviewer=is_admin_reviewer(request.user), theme_review=True
        ).filter(status__in=(amo.STATUS_NOMINATED,))


class UpdatedThemesQueueTable(NewThemesQueueTable):
    title = '🎨 Updates'
    urlname = 'queue_theme_pending'
    url = r'^theme_updates$'

    @classmethod
    def get_queryset(cls, request, **kw):
        return Addon.objects.get_queryset_for_pending_queues(
            admin_reviewer=is_admin_reviewer(request.user), theme_review=True
        ).filter(status__in=(amo.STATUS_APPROVED,))


class PendingRejectionTable(AddonQueueTable):
    deadline = tables.Column(
        verbose_name='Pending Rejection Deadline',
        accessor='first_version_pending_rejection_date',
    )
    code_weight = tables.Column(
        verbose_name='Code Weight',
        accessor='first_pending_version__autoapprovalsummary__code_weight',
    )
    metadata_weight = tables.Column(
        verbose_name='Metadata Weight',
        accessor='first_pending_version__autoapprovalsummary__metadata_weight',
    )
    weight = tables.Column(
        verbose_name='Total Weight',
        accessor='first_pending_version__autoapprovalsummary__weight',
    )
    score = tables.Column(
        verbose_name='Maliciousness Score',
        accessor='first_pending_version__autoapprovalsummary__score',
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
            'code_weight',
            'metadata_weight',
            'weight',
            'score',
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
        exclude = (
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
        )
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


class ModerationQueueFields:
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
        self, *, addon, version=None, user=None, content_review=False, human_review=True
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
        is_admin_needed = (
            self.addon.needs_admin_content_review or self.addon.needs_admin_code_review
        )
        is_admin_needed_post_review = is_admin_needed

        # More complex/specific cases.
        if promoted_group == RECOMMENDED:
            permission = amo.permissions.ADDONS_RECOMMENDED_REVIEW
            permission_post_review = permission
        elif version_is_unlisted:
            is_admin_needed = self.addon.needs_admin_code_review
            permission = amo.permissions.ADDONS_REVIEW_UNLISTED
            permission_post_review = permission
        elif promoted_group.admin_review:
            is_admin_needed = is_admin_needed_post_review = True
        elif self.content_review:
            is_admin_needed = self.addon.needs_admin_content_review
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

        has_needs_human_review = (
            self.version
            and NeedsHumanReview.objects.filter(
                version__addon=self.addon, version__channel=self.version.channel
            ).exists()
        )

        # Definitions for all actions.
        boilerplate_for_approve = 'Thank you for your contribution.'
        boilerplate_for_reject = (
            "This add-on didn't pass review because of the following problems:\n\n1) "
        )

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
            'requires_reasons': False,
            'boilerplate_text': boilerplate_for_approve,
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
            'requires_reasons': not is_static_theme,
            'boilerplate_text': boilerplate_for_reject,
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
        }
        actions['reject_multiple_versions'] = {
            'method': self.handler.reject_multiple_versions,
            'label': 'Reject Multiple Versions',
            'minimal': True,
            'delayable': (
                # Either the version is listed
                not version_is_unlisted
                # or (unlisted and) awaiting review
                or self.version.file.status == amo.STATUS_AWAITING_REVIEW
            ),
            'multiple_versions': True,
            'details': (
                'This will reject the selected versions. '
                'The comments will be sent to the developer.'
            ),
            'available': (can_reject_multiple),
            'allows_reasons': True,
            'requires_reasons': not is_static_theme,
            'boilerplate_text': boilerplate_for_reject,
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
        }
        actions['reply'] = {
            'method': self.handler.reviewer_reply,
            'label': 'Reviewer reply',
            'details': (
                'This will send a message to the developer. '
                'You will be notified when they reply.'
            ),
            'minimal': True,
            'available': (
                self.version is not None
                and is_reviewer
                and (not promoted_group.admin_review or is_appropriate_reviewer)
            ),
            'allows_reasons': not is_static_theme,
            'requires_reasons': False,
        }
        actions['super'] = {
            'method': self.handler.process_super_review,
            'label': 'Request super-review',
            'details': (
                'If you have concerns about this add-on that '
                'an admin reviewer should look into, enter '
                'your comments in the area below. They will '
                'not be sent to the developer.'
            ),
            'minimal': True,
            'available': (self.version is not None and is_reviewer),
        }
        actions['comment'] = {
            'method': self.handler.process_comment,
            'label': 'Comment',
            'details': (
                'Make a comment on this version. The developer '
                "won't be able to see this."
            ),
            'minimal': True,
            'available': (is_reviewer),
        }
        actions['clear_needs_human_review'] = {
            'method': self.handler.clear_needs_human_review,
            'label': 'Clear Needs Human Review',
            'details': (
                'Clear needs human review flag from all versions in this channel, but '
                "otherwise don't change the version(s) or add-on statuses."
            ),
            'minimal': True,
            'comments': False,
            'available': (is_appropriate_admin_reviewer and has_needs_human_review),
        }
        return OrderedDict(
            ((key, action) for key, action in actions.items() if action['available'])
        )

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()


class ReviewBase:
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

    def clear_all_needs_human_review_flags_in_channel(self, mad_too=True):
        """Clear needs_human_review flags on all versions in the same channel.

        To be called when approving a listed version: For listed, the version
        reviewers are approving is always the latest listed one, and then users
        are supposed to automatically get the update to that version, so we
        don't need to care about older ones anymore.

        Also used by clear_needs_human_review action for unlisted too.
        """
        # Do a mass UPDATE.
        NeedsHumanReview.objects.filter(
            version__addon=self.addon,
            version__channel=self.version.channel,
            is_active=True,
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

    def clear_specific_needs_human_review_flags(self, version):
        """Clear needs_human_review flags on a specific version."""
        version.needshumanreview_set.filter(is_active=True).update(is_active=False)
        if version.needs_human_review_by_mad:
            version.reviewerflags.update(needs_human_review_by_mad=False)
        # Because the updating of needs human review was made with a queryset
        # the post_save signal was not triggered so let's recheck the due date
        # explicitly.
        version.reset_due_date()

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
    ):
        details = {
            'comments': self.data.get('comments', ''),
            'reviewtype': self.review_type.split('_')[1],
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

        args = (*args, *self.data.get('reasons', []))
        kwargs = {'user': user or self.user, 'created': timestamp, 'details': details}
        self.log_entry = ActivityLog.create(action, *args, **kwargs)

    def notify_email(
        self, template, subject, perm_setting='reviewer_reviewed', version=None
    ):
        """Notify the authors that their addon has been reviewed."""
        if version is None:
            version = self.version
        data = self.data.copy() if self.data else {}
        data.update(self.get_context_data())
        data['tested'] = ''
        os, app = data.get('operating_systems'), data.get('applications')
        if os and app:
            data['tested'] = f'Tested on {os} with {app}'
        elif os and not app:
            data['tested'] = 'Tested on %s' % os
        elif not os and app:
            data['tested'] = 'Tested with %s' % app
        subject = subject % (data['name'], self.version.version if self.version else '')
        unique_id = (
            self.log_entry.id
            if hasattr(self, 'log_entry')
            else random.randrange(100000)
        )

        message = loader.get_template('reviewers/emails/%s.ltxt' % template).render(
            data
        )
        send_activity_mail(
            subject,
            message,
            version,
            self.addon.authors.all(),
            settings.ADDONS_EMAIL,
            unique_id,
            perm_setting=perm_setting,
        )

    def get_context_data(self):
        addon_url = self.addon.get_url_path(add_prefix=False)
        # We need to display the name in some language that is relevant to the
        # recipient(s) instead of using the reviewer's. addon.default_locale
        # should work.
        if self.addon.name and self.addon.name.locale != self.addon.default_locale:
            lang = to_language(self.addon.default_locale)
            with translation.override(lang):
                # Force a reload of translations for this addon.
                addon = Addon.unfiltered.get(pk=self.addon.pk)
        else:
            addon = self.addon
        review_url_kw = {'addon_id': self.addon.pk}
        if self.version and self.version.channel == amo.CHANNEL_UNLISTED:
            review_url_kw['channel'] = 'unlisted'
            dev_ver_url = reverse('devhub.addons.versions', args=[self.addon.id])
        else:
            dev_ver_url = self.addon.get_dev_url('versions')
        return {
            'name': addon.name,
            'number': self.version.version if self.version else '',
            'addon_url': absolutify(addon_url),
            'dev_versions_url': absolutify(dev_ver_url),
            'review_url': absolutify(
                reverse('reviewers.review', kwargs=review_url_kw, add_prefix=False)
            ),
            'comments': self.data.get('comments'),
            'SITE_URL': settings.SITE_URL,
        }

    def reviewer_reply(self):
        # Default to reviewer reply action.
        action = amo.LOG.REVIEWER_REPLY_VERSION
        log.info(
            'Sending reviewer reply for %s to authors and other'
            'recipients' % self.addon
        )
        self.log_action(action)
        notify_about_activity_log(
            self.addon, self.version, self.log_entry, perm_setting='individual_contact'
        )

    def sign_file(self):
        assert not (self.version and self.version.is_blocked)
        if self.file:
            if self.file.is_experiment:
                ActivityLog.create(amo.LOG.EXPERIMENT_SIGNED, self.file, user=self.user)
            sign_file(self.file)

    def process_comment(self):
        self.log_action(amo.LOG.COMMENT_VERSION)

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
        template = '%s_to_approved' % self.review_type
        if self.review_type in ['extension_pending', 'theme_pending']:
            subject = 'Mozilla Add-ons: %s %s Updated'
        else:
            subject = 'Mozilla Add-ons: %s %s Approved'
        self.notify_email(template, subject)

        self.log_public_message()
        log.info('Sending email for %s' % (self.addon))

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
        template = '%s_to_rejected' % self.review_type
        subject = "Mozilla Add-ons: %s %s didn't pass review"
        self.notify_email(template, subject)

        self.log_sandbox_message()
        log.info('Sending email for %s' % (self.addon))

    def process_super_review(self):
        """Mark an add-on as needing admin code, content, or theme review."""
        addon_type = self.addon.type

        if addon_type == amo.ADDON_STATICTHEME:
            needs_admin_property = 'needs_admin_theme_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_THEME
        elif self.content_review:
            needs_admin_property = 'needs_admin_content_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_CONTENT
        else:
            needs_admin_property = 'needs_admin_code_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_CODE

        AddonReviewerFlags.objects.update_or_create(
            addon=self.addon, defaults={needs_admin_property: True}
        )

        self.log_action(log_action_type)
        log.info(f'{log_action_type.short} for {self.addon}')

    def approve_content(self):
        """Approve content of an add-on."""
        channel = self.version.channel
        version = self.addon.current_version

        # Content review only action.
        assert self.content_review

        # Doesn't make sense for unlisted versions.
        assert channel == amo.CHANNEL_LISTED

        # Like confirm auto approval, the approve content action should not
        # show the comment box, so override the text in case the reviewer
        # switched between actions and accidently submitted some comments from
        # another action.
        self.data['comments'] = ''

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
        # The confirm auto-approval action should not show the comment box,
        # so override the text in case the reviewer switched between actions
        # and accidently submitted some comments from another action.
        self.data['comments'] = ''

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

    def reject_multiple_versions(self):
        """Reject a list of versions.
        Note: this is used in blocklist.utils.disable_addon_for_block for both
        listed and unlisted versions (human_review=False)."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        latest_version = self.version
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
                    amo.LOG.REJECT_CONTENT
                    if flags.pending_content_rejection
                    else amo.LOG.REJECT_VERSION
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
        for action_id, user_and_versions in actions_to_record.items():
            for user, versions in user_and_versions.items():
                self.log_action(
                    action_id,
                    versions=versions,
                    timestamp=now,
                    user=user,
                )

        # A rejection (delayed or not) implies the next version should be
        # manually reviewed.
        auto_approval_disabled_until_next_approval_flag = (
            'auto_approval_disabled_until_next_approval'
            if channel == amo.CHANNEL_LISTED
            else 'auto_approval_disabled_until_next_approval_unlisted'
        )
        addonreviewerflags = {
            auto_approval_disabled_until_next_approval_flag: True,
        }
        if pending_rejection_deadline:
            # Developers should be notified again once the deadline is close.
            addonreviewerflags['notified_about_expiring_delayed_rejections'] = False
        else:
            # An immediate rejection might require the add-on status to change.
            self.addon.update_status()
        AddonReviewerFlags.objects.update_or_create(
            addon=self.addon,
            defaults=addonreviewerflags,
        )

        # Assign reviewer incentive scores and send email, if it's an human
        # reviewer: if it's not, it's coming from some automation where we
        # don't need to notify the developer (we should already have done that
        # before) and don't need to award points.
        if self.human_review:
            channel = latest_version.channel
            # Send the email to the developer. We need to pass the latest
            # version of the add-on instead of one of the versions we rejected,
            # it will be used to generate a token allowing the developer to
            # reply, and that only works with the latest version.
            self.data['version_numbers'] = ', '.join(
                str(v.version) for v in self.data['versions']
            )
            if pending_rejection_deadline:
                template = 'reject_multiple_versions_with_delay'
                subject = 'Mozilla Add-ons: %s%s will be disabled on addons.mozilla.org'
            elif (
                self.addon.status != amo.STATUS_APPROVED
                and channel == amo.CHANNEL_LISTED
            ):
                template = 'reject_multiple_versions_disabled_addon'
                subject = (
                    'Mozilla Add-ons: %s%s has been disabled on addons.mozilla.org'
                )
            else:
                template = 'reject_multiple_versions'
                subject = 'Mozilla Add-ons: Versions disabled for %s%s'
            log.info('Sending email for %s' % (self.addon))
            self.notify_email(template, subject, version=latest_version)

            # The reviewer should be automatically subscribed to any new
            # versions posted to the same channel.
            ReviewerSubscription.objects.get_or_create(
                user=self.user, addon=self.addon, channel=latest_version.channel
            )

    def unreject_latest_version(self):
        """Un-reject the latest version."""
        # we're only supporting non-automated reviews right now:
        assert self.human_review

        log.info(
            'Making %s versions %s awaiting review (not disabled)'
            % (self.addon, self.version.pk)
        )

        self.set_file(amo.STATUS_AWAITING_REVIEW, self.version.file)
        self.log_action(action=amo.LOG.UNREJECT_VERSION)
        self.addon.update_status(self.user)

    def confirm_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def approve_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def block_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def unreject_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def clear_needs_human_review(self):
        """clears human review all versions in this channel."""
        self.clear_all_needs_human_review_flags_in_channel(mad_too=False)
        channel = amo.CHANNEL_CHOICES_API.get(self.version.channel)
        self.version = None  # we don't want to associate the log with a version
        self.log_action(
            amo.LOG.CLEAR_NEEDS_HUMAN_REVIEWS, extra_details={'channel': channel}
        )


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
            ActivityLog.create(amo.LOG.UNLISTED_SIGNED, self.file, user=self.user)

        self.set_file(amo.STATUS_APPROVED, self.file)

        template = 'unlisted_to_reviewed_auto'
        subject = 'Mozilla Add-ons: %s %s signed and ready to download'
        self.log_action(amo.LOG.APPROVE_VERSION)

        if self.human_review:
            self.set_promoted()
            self.clear_specific_needs_human_review_flags(self.version)

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
                reason=NeedsHumanReview.REASON_AUTO_APPROVED_PAST_APPROVAL_DELAY,
            )

        self.notify_email(template, subject, perm_setting=None)

        log.info(
            'Making %s files %s public'
            % (self.addon, self.file.file.name if self.file else '')
        )
        log.info('Sending email for %s' % (self.addon))

    def block_multiple_versions(self):
        min_version = ('0', None)
        max_version = ('*', None)
        for version in self.data['versions']:
            version_str = version.version
            if not min_version[1] or version_str < min_version[1]:
                min_version = (version, version_str)
            if not max_version[1] or version_str > max_version[1]:
                max_version = (version, version_str)

        params = f'?min={min_version[0].pk}&max={max_version[0].pk}'
        self.redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.pk,)) + params
        )

    def confirm_multiple_versions(self):
        """Confirm approval on a list of versions."""
        # There shouldn't be any comments for this action.
        self.data['comments'] = ''
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

    def approve_multiple_versions(self):
        """Set multiple unlisted add-on versions files to public."""
        assert self.version.channel == amo.CHANNEL_UNLISTED
        latest_version = self.version
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
            ActivityLog.create(amo.LOG.UNLISTED_SIGNED, version.file, user=self.user)
            self.set_file(amo.STATUS_APPROVED, version.file)
            if self.human_review:
                self.clear_specific_needs_human_review_flags(version)
            log.info('Making %s files %s public' % (self.addon, version.file.file.name))

        self.log_action(
            amo.LOG.APPROVE_VERSION, versions=self.data['versions'], timestamp=timestamp
        )

        if self.human_review:
            self.set_promoted(versions=self.data['versions'])
            template = 'approve_multiple_versions'
            subject = 'Mozilla Add-ons: %s%s signed and ready to download'
            self.data['version_numbers'] = ', '.join(
                str(v.version) for v in self.data['versions']
            )

            self.notify_email(
                template, subject, perm_setting=None, version=latest_version
            )
            log.info('Sending email(s) for %s' % (self.addon))

            # An approval took place so we can reset this.
            AddonReviewerFlags.objects.update_or_create(
                addon=self.addon,
                defaults={'auto_approval_disabled_until_next_approval_unlisted': False},
            )

    def unreject_multiple_versions(self):
        """Un-reject a list of versions."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        self.version = None
        self.file = None
        now = datetime.now()
        # we're only supporting non-automated reviews right now:
        assert self.human_review

        log.info(
            'Making %s versions %s awaiting review (not disabled)'
            % (self.addon, ', '.join(str(v.pk) for v in self.data['versions']))
        )

        for version in self.data['versions']:
            self.set_file(amo.STATUS_AWAITING_REVIEW, version.file)

        self.log_action(
            action=amo.LOG.UNREJECT_VERSION,
            versions=self.data['versions'],
            timestamp=now,
            user=self.user,
        )

        if self.data['versions']:
            # if these are listed versions then the addon status may need updating
            self.addon.update_status(self.user)
