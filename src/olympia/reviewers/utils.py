import random
from collections import OrderedDict
from datetime import datetime, timedelta

import django_tables2 as tables
import olympia.core.logger
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import Count, F, Q
from django.template import loader
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _

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
    ReviewerScore,
    ReviewerSubscription,
    get_flags,
)
from olympia.reviewers.templatetags.jinja_helpers import format_score
from olympia.users.utils import get_task_user
from olympia.versions.models import VersionReviewerFlags

import markupsafe


log = olympia.core.logger.getLogger('z.mailer')


class ItemStateTable:
    def increment_item(self):
        self.item_number += 1

    def set_page(self, page):
        self.item_number = page.start_index()


def safe_substitute(string, *args):
    return string % tuple(markupsafe.escape(arg) for arg in args)


class ViewUnlistedAllListTable(tables.Table, ItemStateTable):
    id = tables.Column(verbose_name=_('ID'))
    addon_name = tables.Column(
        verbose_name=_('Add-on'), accessor='name', orderable=False
    )
    guid = tables.Column(verbose_name=_('GUID'))
    show_count_in_dashboard = False

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.unfiltered.get_addons_with_unlisted_versions_queue(
            admin_reviewer=True
        )

    def render_addon_name(self, record):
        url = reverse(
            'reviewers.review',
            args=[
                'unlisted',
                record.id,
            ],
        )
        self.increment_item()
        return markupsafe.Markup(
            safe_substitute('<a href="%s">%s</a>', url, record.name)
        )

    def render_guid(self, record):
        return markupsafe.Markup(safe_substitute('%s', record.guid))

    @classmethod
    def default_order_by(cls):
        return '-id'


class AddonQueueTable(tables.Table, ItemStateTable):
    addon_name = tables.Column(
        verbose_name=_('Add-on'), accessor='name', orderable=False
    )
    # Override empty_values for flags so that they can be displayed even if the
    # model does not have a flags attribute.
    flags = tables.Column(verbose_name=_('Flags'), empty_values=(), orderable=False)
    last_human_review = tables.DateTimeColumn(
        verbose_name=_('Last Review'),
        accessor='addonapprovalscounter__last_human_review',
    )
    code_weight = tables.Column(
        verbose_name=_('Code Weight'),
        accessor='_current_version__autoapprovalsummary__code_weight',
    )
    metadata_weight = tables.Column(
        verbose_name=_('Metadata Weight'),
        accessor='_current_version__autoapprovalsummary__metadata_weight',
    )
    weight = tables.Column(
        verbose_name=_('Total Weight'),
        accessor='_current_version__autoapprovalsummary__weight',
    )
    score = tables.Column(
        verbose_name=_('Maliciousness Score'),
        accessor='_current_version__autoapprovalsummary__score',
    )
    show_count_in_dashboard = True

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

    def render_flags(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags(record, record.current_version)
        return markupsafe.Markup(
            ''.join(
                '<div class="app-icon ed-sprite-%s" title="%s"></div>' % flag
                for flag in record.flags
            )
        )

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=[record.id])

    def render_addon_name(self, record):
        url = self._get_addon_name_url(record)
        return markupsafe.Markup(
            '<a href="%s">%s <em>%s</em></a>'
            % (
                url,
                markupsafe.escape(record.name),
                markupsafe.escape(record.current_version),
            )
        )

    def render_last_human_review(self, value):
        return naturaltime(value) if value else ''

    def render_weight(self, *, record, value):
        return markupsafe.Markup(
            '<span title="%s">%d</span>'
            % (
                '\n'.join(
                    record.current_version.autoapprovalsummary.get_pretty_weight_info()
                ),
                value,
            )
        )

    def render_score(self, value):
        return format_score(value)

    render_last_content_review = render_last_human_review


class PendingManualApprovalQueueTable(AddonQueueTable):
    addon_type = tables.Column(verbose_name=_('Type'), accessor='type', orderable=False)
    waiting_time = tables.Column(
        verbose_name=_('Waiting Time'), accessor='first_version_nominated'
    )

    class Meta:
        fields = ('addon_name', 'addon_type', 'waiting_time', 'flags')
        exclude = (
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
            'score',
        )

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_listed_pending_manual_approval_queue(
            admin_reviewer=admin_reviewer
        )

    def _get_waiting_time(self, record):
        return record.first_version_nominated

    def render_addon_name(self, record):
        url = self._get_addon_name_url(record)
        self.increment_item()
        return markupsafe.Markup(
            '<a href="%s">%s <em>%s</em></a>'
            % (
                url,
                markupsafe.escape(record.name),
                markupsafe.escape(getattr(record, 'latest_version', '')),
            )
        )

    def render_addon_type(self, record):
        return record.get_type_display()

    def render_waiting_time(self, record):
        return markupsafe.Markup(
            f'<span title="{markupsafe.escape(self._get_waiting_time(record))}">'
            f'{markupsafe.escape(naturaltime(self._get_waiting_time(record)))}</span>'
        )

    @classmethod
    def default_order_by(cls):
        # waiting_time column is actually the date from the minimum version
        # creation/nomination date. We want to display the add-ons which have
        # waited the longest at the top by default, so we return waiting_time
        # in ascending order.
        return 'waiting_time'


class RecommendedPendingManualApprovalQueueTable(PendingManualApprovalQueueTable):
    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_listed_pending_manual_approval_queue(
            admin_reviewer=admin_reviewer, recommendable=True
        )


class NewThemesQueueTable(PendingManualApprovalQueueTable):
    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_listed_pending_manual_approval_queue(
            admin_reviewer=admin_reviewer,
            statuses=(amo.STATUS_NOMINATED,),
            types=amo.GROUP_TYPE_THEME,
        )


class UpdatedThemesQueueTable(NewThemesQueueTable):
    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_listed_pending_manual_approval_queue(
            admin_reviewer=admin_reviewer,
            statuses=(amo.STATUS_APPROVED,),
            types=amo.GROUP_TYPE_THEME,
        )


class UnlistedPendingManualApprovalQueueTable(PendingManualApprovalQueueTable):
    waiting_time = tables.Column(
        verbose_name=_('Waiting Time'), accessor='first_version_created'
    )
    score = tables.Column(verbose_name=_('Maliciousness Score'), accessor='worst_score')
    show_count_in_dashboard = False

    class Meta(PendingManualApprovalQueueTable.Meta):
        fields = (
            'addon_name',
            'addon_type',
            'waiting_time',
            'score',
        )
        exclude = (
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
            'flags',
        )

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=['unlisted', record.id])

    def _get_waiting_time(self, record):
        return record.first_version_created

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_unlisted_pending_manual_approval_queue(
            admin_reviewer=admin_reviewer
        )

    @classmethod
    def default_order_by(cls):
        return '-score'


class PendingRejectionTable(AddonQueueTable):
    deadline = tables.Column(
        verbose_name=_('Pending Rejection Deadline'),
        accessor='_current_version__reviewerflags__pending_rejection',
    )

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
        exclude = ('waiting_time',)

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_pending_rejection_queue(admin_reviewer=admin_reviewer)

    def render_deadline(self, value):
        return naturaltime(value) if value else ''

    def render_addon_name(self, record):
        url = self._get_addon_name_url(record)
        self.increment_item()
        return markupsafe.Markup(
            '<a href="%s">%s'
            % (
                url,
                markupsafe.escape(record.name),
            )
        )


class AutoApprovedTable(AddonQueueTable):
    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_auto_approved_queue(admin_reviewer=admin_reviewer)


class ContentReviewTable(AutoApprovedTable):
    last_updated = tables.DateTimeColumn(verbose_name=_('Last Updated'))

    class Meta(AutoApprovedTable.Meta):
        fields = ('addon_name', 'flags', 'last_updated')
        # Exclude base fields AutoApprovedTable has that we don't want.
        exclude = (
            'last_human_review',
            'code_weight',
            'metadata_weight',
            'weight',
        )
        orderable = False

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_content_review_queue(admin_reviewer=admin_reviewer)

    def render_last_updated(self, value):
        return naturaltime(value) if value else ''

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=['content', record.id])


class HumanReviewTable(AddonQueueTable):
    listed_text = _('Listed versions needing human review ({0})')
    unlisted_text = _('Unlisted versions needing human review ({0})')
    show_count_in_dashboard = False

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_human_review_queue(
            admin_reviewer=admin_reviewer
        ).annotate(
            unlisted_versions_that_need_human_review=Count(
                'versions',
                filter=Q(
                    versions__needs_human_review=True,
                    versions__channel=amo.CHANNEL_UNLISTED,
                ),
            ),
            listed_versions_that_need_human_review=Count(
                'versions',
                filter=Q(
                    versions__needs_human_review=True,
                    versions__channel=amo.CHANNEL_LISTED,
                ),
            ),
        )

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


class MadReviewTable(HumanReviewTable):
    listed_text = _('Listed version')
    unlisted_text = _('Unlisted versions ({0})')
    show_count_in_dashboard = False

    @classmethod
    def get_queryset(cls, admin_reviewer=False):
        return Addon.objects.get_mad_queue(admin_reviewer=admin_reviewer).annotate(
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
        is_admin_reviewer = is_appropriate_reviewer and acl.action_allowed_for(
            self.user, amo.permissions.REVIEWS_ADMIN
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
        addon_is_valid = self.addon.is_public() or self.addon.is_unreviewed()
        addon_is_valid_and_version_is_listed = (
            addon_is_valid
            and self.version
            and self.version.channel == amo.CHANNEL_LISTED
        )
        current_version_is_listed_and_auto_approved = (
            self.version
            and self.version.channel == amo.CHANNEL_LISTED
            and self.addon.current_version
            and self.addon.current_version.was_auto_approved
        )
        version_is_blocked = self.version and self.version.is_blocked

        # Special logic for availability of reject/approve multiple action:
        if version_is_unlisted:
            can_reject_multiple = is_appropriate_reviewer
            can_approve_multiple = is_appropriate_reviewer
        elif self.content_review or promoted_group.pre_review or is_static_theme:
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
        boilerplate_for_approve = 'Thank you for your contribution.'
        boilerplate_for_reject = (
            "This add-on didn't pass review because of the following problems:\n\n1) "
        )

        actions['public'] = {
            'method': self.handler.approve_latest_version,
            'minimal': False,
            'details': _(
                'This will approve, sign, and publish this '
                'version. The comments will be sent to the '
                'developer.'
            ),
            'label': _('Approve'),
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
            'label': _('Reject'),
            'details': _(
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
            'label': _('Approve Content'),
            'details': _(
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
            'label': _('Confirm Approval'),
            'details': _(
                'The latest public version of this add-on was '
                'automatically approved. This records your '
                'confirmation of the approval of that version, '
                'without notifying the developer.'
            ),
            'minimal': True,
            'comments': False,
            'available': (
                not self.content_review
                and addon_is_valid_and_version_is_listed
                and current_version_is_listed_and_auto_approved
                and is_appropriate_reviewer_post_review
            ),
        }
        actions['approve_multiple_versions'] = {
            'method': self.handler.approve_multiple_versions,
            'label': _('Approve Multiple Versions'),
            'minimal': True,
            'multiple_versions': True,
            'details': _(
                'This will approve the selected versions. '
                'The comments will be sent to the developer.'
            ),
            'available': (can_approve_multiple),
            'allows_reasons': not is_static_theme,
            'requires_reasons': False,
        }
        actions['reject_multiple_versions'] = {
            'method': self.handler.reject_multiple_versions,
            'label': _('Reject Multiple Versions'),
            'minimal': True,
            'delayable': (
                # Either the version is listed
                not version_is_unlisted
                # or (unlisted and) awaiting review
                or self.version.file.status == amo.STATUS_AWAITING_REVIEW
            ),
            'multiple_versions': True,
            'details': _(
                'This will reject the selected versions. '
                'The comments will be sent to the developer.'
            ),
            'available': (can_reject_multiple),
            'allows_reasons': True,
            'requires_reasons': not is_static_theme,
            'boilerplate_text': boilerplate_for_reject,
        }
        actions['unreject_multiple_versions'] = {
            'method': self.handler.unreject_multiple_versions,
            'label': _('Un-reject Versions'),
            'minimal': True,
            'multiple_versions': True,
            'details': _(
                'This will un-reject the selected versions without notifying the '
                'developer.'
            ),
            'comments': False,
            'available': (addon_is_not_disabled_or_deleted and is_admin_reviewer),
        }
        actions['block_multiple_versions'] = {
            'method': self.handler.block_multiple_versions,
            'label': _('Block Multiple Versions'),
            'minimal': True,
            'multiple_versions': True,
            'comments': False,
            'details': _(
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
            'label': _('Confirm Multiple Versions'),
            'minimal': True,
            'multiple_versions': True,
            'details': _(
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
            'label': _('Reviewer reply'),
            'details': _(
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
            'requires_reasons': not is_static_theme,
        }
        actions['super'] = {
            'method': self.handler.process_super_review,
            'label': _('Request super-review'),
            'details': _(
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
            'label': _('Comment'),
            'details': _(
                'Make a comment on this version. The developer '
                "won't be able to see this."
            ),
            'minimal': True,
            'available': (is_reviewer),
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

    def set_addon(self, **kw):
        """Alter addon, set reviewed timestamp on version being reviewed."""
        self.addon.update(**kw)
        self.version.update(reviewed=datetime.now())

    def set_data(self, data):
        self.data = data

    def set_file(self, status, file):
        """Change the file to be the new status."""
        file.datestatuschanged = datetime.now()
        file.reviewed = datetime.now()
        file.status = status
        file.save()

    def set_promoted(self):
        group = self.addon.promoted_group(currently_approved=False)
        if group and group.pre_review:
            # These addons shouldn't be be attempted for auto approval anyway,
            # but double check that the cron job isn't trying to approve it.
            assert not self.user.id == settings.TASK_USER_ID
            self.addon.promotedaddon.approve_for_version(self.version)

    def clear_all_needs_human_review_flags_in_channel(self):
        """Clear needs_human_review flags on all versions in the same channel.

        To be called when approving a listed version: For listed, the version
        reviewers are approving is always the latest listed one, and then users
        are supposed to automatically get the update to that version, so we
        don't need to care about older ones anymore.
        """
        # Do a mass UPDATE.
        self.addon.versions.filter(
            needs_human_review=True, channel=self.version.channel
        ).update(needs_human_review=False)
        # Another one for the needs_human_review_by_mad flag.
        VersionReviewerFlags.objects.filter(
            version__addon=self.addon,
            version__channel=self.version.channel,
        ).update(needs_human_review_by_mad=False)
        # Also reset it on self.version in case this instance is saved later.
        self.version.needs_human_review = False

    def clear_specific_needs_human_review_flags(self, version):
        """Clear needs_human_review flags on a specific version."""
        if version.needs_human_review:
            version.update(needs_human_review=False)
        if version.needs_human_review_by_mad:
            version.reviewerflags.update(needs_human_review_by_mad=False)

    def log_action(self, action, version=None, file=None, timestamp=None, user=None):
        details = {
            'comments': self.data.get('comments', ''),
            'reviewtype': self.review_type.split('_')[1],
        }
        if file is None and self.file:
            file = self.file
        if file is not None:
            details['files'] = [file.id]
        if version is None and self.version:
            version = self.version
        if version is not None:
            details['version'] = version.version
            args = (self.addon, version)
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
        if self.version:
            if (
                self.version.channel == amo.CHANNEL_UNLISTED
                and not self.version.reviewed
            ):
                self.version.update(reviewed=datetime.now())

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
        update_reviewed = (
            self.version
            and self.version.channel == amo.CHANNEL_UNLISTED
            and not self.version.reviewed
        )
        if update_reviewed:
            self.version.update(reviewed=datetime.now())

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

        # Hold onto the status before we change it.
        status = self.addon.status

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_file(amo.STATUS_APPROVED, self.file)
        self.set_promoted()
        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_APPROVED)

        if self.human_review:
            # No need for a human review anymore in this channel.
            self.clear_all_needs_human_review_flags_in_channel()

            # Clear pending rejection since we approved that version.
            VersionReviewerFlags.objects.filter(version=self.version,).update(
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

            # Assign reviewer incentive scores.
            ReviewerScore.award_points(
                self.user, self.addon, status, version=self.version
            )
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

        # Hold onto the status before we change it.
        status = self.addon.status

        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_NULL)
        self.set_file(amo.STATUS_DISABLED, self.file)

        if self.human_review:
            # Clear needs human review flags, but only on the latest version:
            # it's the only version we can be certain that the reviewer looked
            # at.
            self.clear_specific_needs_human_review_flags(self.version)

            # Assign reviewer incentive scores.
            ReviewerScore.award_points(
                self.user, self.addon, status, version=self.version
            )

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

        # Assign reviewer incentive scores.
        if self.human_review:
            is_post_review = channel == amo.CHANNEL_LISTED
            ReviewerScore.award_points(
                self.user,
                self.addon,
                self.addon.status,
                version=version,
                post_review=is_post_review,
                content_review=self.content_review,
            )

    def confirm_auto_approved(self):
        """Confirm an auto-approval decision."""

        channel = self.version.channel
        if channel == amo.CHANNEL_LISTED:
            # When doing an approval in listed channel, the version we care
            # about is always current_version and *not* self.version.
            # This allows reviewers to confirm approval of a public add-on even
            # when their latest version is disabled.
            version = self.addon.current_version
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

            # Assign reviewer incentive scores.
            is_post_review = channel == amo.CHANNEL_LISTED
            ReviewerScore.award_points(
                self.user,
                self.addon,
                self.addon.status,
                version=version,
                post_review=is_post_review,
                content_review=self.content_review,
            )

    def reject_multiple_versions(self):
        """Reject a list of versions.
        Note: this is used in blocklist.utils.disable_addon_for_block for both
        listed and unlisted versions (human_review=False)."""
        # self.version and self.file won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        status = self.addon.status
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
            self.log_action(
                action_id,
                version=version,
                file=file,
                timestamp=now,
                user=version.pending_rejection_by,
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

            ReviewerScore.award_points(
                self.user,
                self.addon,
                status,
                version=latest_version,
                post_review=True,
                content_review=self.content_review,
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
                version=version,
                file=version.file,
                timestamp=now,
                user=self.user,
            )

        if self.data['versions']:
            # if these are listed versions then the addon status may need updating
            self.addon.update_nominated_status(self.user)

    def notify_about_auto_approval_delay(self, version):
        """Notify developers of the add-on when their version has not been
        auto-approved for a while."""
        template = 'held_for_review'
        subject = 'Mozilla Add-ons: %s %s is pending review'
        AddonReviewerFlags.objects.update_or_create(
            addon=self.addon, defaults={'notified_about_auto_approval_delay': True}
        )
        self.data['version'] = version
        self.notify_email(template, subject, version=version)

    def confirm_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def approve_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.

    def block_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.


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

        timestamp = datetime.now()
        for version in self.data['versions']:
            self.log_action(
                amo.LOG.CONFIRM_AUTO_APPROVED, version=version, timestamp=timestamp
            )
            if self.human_review:
                # Mark summary as confirmed if it exists.
                try:
                    version.autoapprovalsummary.update(confirmed=True)
                except AutoApprovalSummary.DoesNotExist:
                    pass
                # Clear needs_human_review on rejected versions, we consider
                # that the reviewer looked at all versions they are approving.
                self.clear_specific_needs_human_review_flags(version)

    def approve_multiple_versions(self):
        """Set multiple unlisted add-on versions files to public."""
        assert self.version.channel == amo.CHANNEL_UNLISTED
        latest_version = self.version
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
            self.log_action(
                amo.LOG.APPROVE_VERSION, version, version.file, timestamp=timestamp
            )
            if self.human_review:
                self.clear_specific_needs_human_review_flags(version)

            log.info('Making %s files %s public' % (self.addon, version.file.file.name))

        if self.human_review:
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
