import random
from collections import defaultdict
from datetime import datetime, timedelta
from inspect import isclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.template import loader
from django.urls import reverse
from django.utils import translation
from django.utils.functional import classproperty
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

import olympia
from olympia import amo
from olympia.access.models import Group
from olympia.activity import log_create
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block, BlocklistSubmission, BlockType
from olympia.blocklist.utils import delete_versions_from_blocks, save_versions_to_blocks
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.blocklist import BlockReason
from olympia.constants.permissions import ADDONS_HIGH_IMPACT_APPROVE
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.files.models import File
from olympia.lib.crypto.signing import sign_file
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags


POLICY_DOCUMENT_URL = (
    'https://extensionworkshop.com/documentation/publish/add-on-policies/'
)

log = olympia.core.logger.getLogger('z.abuse')


class ContentAction:
    description = 'Action has been taken'
    valid_targets = ()
    # No reporter emails will be sent while the paths are set to None
    reporter_template_path = None
    reporter_appeal_template_path = None
    second_level_notification_template_path = (
        'abuse/emails/second_level_notification.txt'
    )
    action = None

    def __init__(self, decision):
        self.decision = decision
        self.target = self.decision.target

        if isinstance(self.target, Addon):
            self.addon_version = (
                (decision.id and decision.target_versions.order_by('-pk').first())
                or self.target.current_version
                or self.target.find_latest_version(channel=None, exclude=())
            )

        if not isinstance(self.target, self.valid_targets):
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} needs a target that is one of '
                f'{self.valid_targets}'
            )

    def log_action(
        self,
        activity_log_action,
        *extra_args,
        extra_details=None,
        skip_private_notes=False,
    ):
        user_kw = (
            {'user': self.decision.reviewer_user} if self.decision.reviewer_user else {}
        )
        if self.decision.private_notes and not skip_private_notes:
            # If the decision contained private notes, add a separate action
            # for them.
            log_create(
                amo.LOG.REVIEWER_PRIVATE_COMMENT,
                self.target,
                self.decision,
                **user_kw,
                details={
                    'comments': self.decision.private_notes,
                },
            )
        return log_create(
            activity_log_action,
            self.target,
            self.decision,
            *(self.decision.policies.all()),
            *extra_args,
            **user_kw,
            details={
                'comments': self.decision.reasoning,
                **(
                    {'policy_texts': self.decision.get_policy_texts()}
                    if not self.decision.has_policy_text_in_comments
                    else {}
                ),
                **(extra_details or {}),
            },
        )

    def should_hold_action(self):
        """This should return false if the action should be processed immediately,
        without further checks, and true if it should be held for further review."""
        return False

    @classmethod
    def should_be_skipped_by_automation(cls, **kwargs):
        """Return True if the action should be skipped by automation for any reason."""
        return False

    def process_action(self, release_hold=False):
        """This method should return an activity log instance for the action,
        if available."""
        raise NotImplementedError

    def hold_action(self):
        """This method should take no action, but create an activity log instance with
        appropriate details."""
        pass

    def get_owners(self):
        """No owner emails will be sent. Override to send owner emails"""
        return ()

    @property
    def owner_template_path(self):
        return f'abuse/emails/{self.__class__.__name__}.txt'

    def notify_owners(self, *, log_entry_id=None, extra_context=None):
        from olympia.activity.utils import send_activity_mail

        owners = self.get_owners()
        if not owners:
            return
        template = loader.get_template(self.owner_template_path)
        target_name = self.decision.get_target_name()
        reference_id = f'ref:{self.decision.get_reference_id()}'
        # override target_url to devhub if there is no public listing
        target_url = (
            self.target.get_absolute_url()
            if not isinstance(self.target, Addon) or self.target.get_url_path()
            else absolutify(reverse('devhub.addons.versions', args=[self.target.id]))
        )

        is_public = (
            # ratings and collections
            not self.target.deleted
            if hasattr(self.target, 'deleted')
            # userprofiles
            else not self.target.banned
            if hasattr(self.target, 'banned')
            # addons
            else callable(getattr(self.target, 'is_public', None))
            and self.target.is_public()
        )

        followups = (
            [
                followup.description_with_eta
                for followup in self.decision.followup_actions.all()
            ]
            if self.decision.id
            else ()
        )

        context_dict = {
            'followups': followups,
            'is_listing_rejected': getattr(self.target, 'status', None)
            == amo.STATUS_REJECTED,
            'is_third_party_initiated': self.decision.is_third_party_initiated,
            # It's a plain-text email so we're safe to include comments without escaping
            # them - we don't want ', etc, rendered as html entities.
            'is_public': is_public,
            'manual_reasoning_text': mark_safe(self.decision.reasoning or ''),
            # It's a plain-text email so we're safe to include the name without escaping
            'name': mark_safe(target_name),
            'policy_document_url': POLICY_DOCUMENT_URL,
            'reference_id': reference_id,
            'target': self.target,
            'target_url': target_url,
            'type': self.decision.get_target_display(),
            'SITE_URL': settings.SITE_URL,
            **(extra_context or {}),
        }
        if 'policy_texts' not in context_dict:
            context_dict['policy_texts'] = self.decision.get_policy_texts()
        if self.decision.can_be_appealed(is_reporter=False):
            context_dict['appeal_url'] = absolutify(
                reverse(
                    'abuse.appeal_author',
                    kwargs={
                        'decision_cinder_id': self.decision.cinder_id,
                    },
                )
            )

        subject = f'Mozilla Add-ons: {target_name} [{reference_id}]'
        message = template.render(context_dict)

        # We send addon related via activity mail instead for the integration
        if version := getattr(self, 'addon_version', None):
            unique_id = log_entry_id or random.randrange(100000)
            send_activity_mail(
                subject,
                message,
                version,
                owners,
                settings.DEFAULT_FROM_EMAIL,
                unique_id,
            )
        else:
            # we didn't manage to find a version to associate with, we have to fall back
            send_mail(subject, message, recipient_list=[user.email for user in owners])

    def notify_reporters(self, *, reporter_abuse_reports, is_appeal=False):
        """Send notification email to reporters.
        reporters is a list of abuse reports that should be notified
        """
        template = (
            self.reporter_template_path
            if not is_appeal
            else self.reporter_appeal_template_path
        )
        if not template or not reporter_abuse_reports:
            return
        template = loader.get_template(template)
        for abuse_report in reporter_abuse_reports:
            email_address = (
                abuse_report.reporter.email
                if abuse_report.reporter
                else abuse_report.reporter_email
            )
            if not email_address:
                continue
            with translation.override(
                abuse_report.application_locale or settings.LANGUAGE_CODE
            ):
                target_name = self.decision.get_target_name()
                reference_id = (
                    f'ref:{self.decision.get_reference_id()}/{abuse_report.id}'
                )
                subject = _('Mozilla Add-ons: {} [{}]').format(
                    target_name, reference_id
                )
                context_dict = {
                    # It's a plain-text email so we're safe to include the name without
                    # escaping it.
                    'name': mark_safe(target_name),
                    'policies': self.decision.policies.all(),
                    'policy_document_url': POLICY_DOCUMENT_URL,
                    'reference_id': reference_id,
                    'target_url': absolutify(self.target.get_url_path()),
                    'type': self.decision.get_target_display(),
                    'SITE_URL': settings.SITE_URL,
                }
                if is_appeal:
                    # It's a plain-text email so we're safe to include comments without
                    # escaping them - we don't want ', etc, rendered as html entities.
                    context_dict['manual_reasoning_text'] = mark_safe(
                        self.decision.reasoning or ''
                    )
                if self.decision.can_be_appealed(
                    is_reporter=True, abuse_report=abuse_report
                ):
                    context_dict['appeal_url'] = absolutify(
                        reverse(
                            'abuse.appeal_reporter',
                            kwargs={
                                'abuse_report_id': abuse_report.id,
                                'decision_cinder_id': (self.decision.cinder_id),
                            },
                        )
                    )
                message = template.render(context_dict)
                send_mail(subject, message, recipient_list=[email_address])

    def notify_2nd_level_approvers(self):
        groups_qs = Group.objects.filter(
            rules__icontains=':'.join(ADDONS_HIGH_IMPACT_APPROVE)
        )
        recipients = [
            user.email for user in UserProfile.objects.filter(groups__in=groups_qs)
        ]
        if not recipients:
            # no recipients, nothing to do
            return
        template = loader.get_template(self.second_level_notification_template_path)
        approval_url = absolutify(
            reverse('reviewers.decision_review', args=[self.decision.id])
        )
        context_dict = {'approval_url': approval_url}
        subject = 'A new item has entered the second level approval queue'
        message = template.render(context_dict)
        send_mail(subject, message, recipient_list=recipients)


class AnyTargetMixin:
    valid_targets = (Addon, UserProfile, Collection, Rating)


class NoActionMixin:
    def process_action(self, release_hold=False):
        return None


class AnyOwnerEmailMixin:
    def get_owners(self):
        target = self.target
        if isinstance(target, Addon):
            return target.authors.all()
        elif isinstance(target, UserProfile):
            return [target]
        elif isinstance(target, Collection):
            return [target.author]
        elif isinstance(target, Rating):
            return [target.user]


class ContentActionBanUser(ContentAction):
    description = 'Account has been banned'
    valid_targets = (UserProfile,)
    reporter_template_path = 'abuse/emails/reporter_takedown_user.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'
    action = DECISION_ACTIONS.AMO_BAN_USER

    def should_hold_action(self):
        return bool(
            not self.target.banned
            and (
                self.target.is_staff  # mozilla.com
                or self.target.groups_list  # has any permissions
                # owns a high profile add-on
                or any(
                    any(addon.promoted_groups(currently_approved=False).high_profile)
                    for addon in self.target.addons.all()
                )
            )
        )

    def process_action(self, release_hold=False):
        if not self.target.banned:
            UserProfile.objects.filter(
                pk=self.target.pk
            ).ban_and_disable_related_content(skip_activity_log=True)
            return self.log_action(amo.LOG.ADMIN_USER_BANNED)

    def hold_action(self):
        if not self.target.banned:
            return self.log_action(amo.LOG.HELD_ACTION_ADMIN_USER_BANNED)

    def get_owners(self):
        return [self.target]


class ContentActionAddon(ContentAction):
    """Base class for content actions for Addons."""

    valid_targets = (Addon,)

    def is_human_reviewer(self):
        return bool(
            (user := self.decision.reviewer_user) and user.id != settings.TASK_USER_ID
        )

    @property
    def target_versions(self):
        return self.decision.target_versions.all()

    def log_action(
        self,
        activity_log_action,
        *extra_args,
        extra_details=None,
        skip_private_notes=False,
    ):
        from olympia.activity.models import AttachmentLog

        extra_details = {'human_review': self.is_human_reviewer()} | (
            extra_details or {}
        )
        if 'versions' not in extra_details and (
            target_versions := self.target_versions.no_transforms()
            .only('pk', 'version', 'file')
            .order_by('-pk')
        ):
            extra_args = (*target_versions, *extra_args)
            extra_details['versions'] = [version.version for version in target_versions]

        activity_log = super().log_action(
            activity_log_action,
            *extra_args,
            extra_details=extra_details,
            skip_private_notes=skip_private_notes,
        )
        # move any attachments to latest decision
        if attachment := AttachmentLog.objects.filter(
            activity_log__contentdecision__id=self.decision.id
        ).first():
            attachment.update(activity_log=activity_log)
            activity_log.attachmentlog = attachment  # update fk
        return activity_log

    def set_human_review_date(self, version):
        if self.is_human_reviewer() and not version.human_review_date:
            version.update(human_review_date=datetime.now())

    def clear_specific_needs_human_review_flags(self, version):
        """Clear needs_human_review flags on a specific version."""
        from olympia.reviewers.models import NeedsHumanReview

        from .models import CinderJob

        qs = version.needshumanreview_set.filter(is_active=True)
        if not hasattr(self, 'unresolved_jobs'):
            # this isn't going to change between iterations, so be efficient
            self.unresolved_jobs = (
                CinderJob.objects.for_addon(self.target)
                .unresolved()
                .resolvable_in_reviewer_tools()
                .exists()
            )
        if self.unresolved_jobs:
            qs = qs.exclude(
                reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values
            )
        qs.update(is_active=False)
        # Because the updating of needs human review was made with a queryset
        # the post_save signal was not triggered so let's recheck the due date
        # explicitly.
        version.reset_due_date()

    def _clear_all_needs_human_review_flags_in_channel(self, channel):
        """Clear needs_human_review flags on all versions in the same channel.

        Doesn't clear abuse or appeal related flags.
        To be called when approving a listed version: For listed, the version
        reviewers are approving is always the latest listed one, and then users
        are supposed to automatically get the update to that version, so we
        don't need to care about older ones anymore.
        """
        from olympia.reviewers.models import NeedsHumanReview

        # Do a mass UPDATE. The NeedsHumanReview coming from abuse/appeal/escalations
        # are only cleared in ContentDecision.execute_action() if the
        # reviewer has selected to resolve all jobs of that type though.
        NeedsHumanReview.objects.filter(
            version__addon=self.target, version__channel=channel, is_active=True
        ).exclude(
            reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values
        ).update(is_active=False)
        # Trigger a check of all due dates on the add-on since we mass-updated
        # versions.
        self.target.update_all_due_dates()


class ContentActionDisableAddon(ContentActionAddon):
    description = 'Add-on has been disabled'
    reporter_template_path = 'abuse/emails/reporter_takedown_addon.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'
    action = DECISION_ACTIONS.AMO_DISABLE_ADDON

    def should_hold_action(self):
        return bool(
            self.target.status != amo.STATUS_DISABLED
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    @property
    def versions_force_disable_will_affect(self):
        return (
            Version.objects.all()
            .filter(addon=self.target)
            .exclude(file__status=amo.STATUS_DISABLED)
            .no_transforms()
            .only('pk', 'version', 'file')
            .order_by('-pk')
        )

    def prevent_auto_approval(self):
        AddonReviewerFlags.objects.update_or_create(
            addon=self.target,
            defaults={
                'auto_approval_disabled': True,
                'auto_approval_disabled_unlisted': True,
            },
        )

    def process_action(self, release_hold=False):
        self.prevent_auto_approval()
        if self.target.status != amo.STATUS_DISABLED:
            # Set target_versions before executing the action, since the
            # queryset depends on the file statuses.
            self.decision.target_versions.set(self.versions_force_disable_will_affect)
            self.target.force_disable(skip_activity_log=True)
            return self.log_action(amo.LOG.FORCE_DISABLE)
        return None

    def hold_action(self):
        self.prevent_auto_approval()
        if self.target.status != amo.STATUS_DISABLED:
            self.decision.target_versions.set(self.versions_force_disable_will_affect)
            return self.log_action(amo.LOG.HELD_ACTION_FORCE_DISABLE)
        return None

    def get_owners(self):
        return self.target.authors.all()


class ContentActionRejectVersion(ContentActionDisableAddon):
    description = 'Add-on version(s) have been rejected'
    stakeholder_template_path = 'abuse/emails/stakeholder_notification.txt'
    stakeholder_acl_group_name = 'Stakeholder-Rejection-Notifications'
    action = DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON

    def __init__(self, decision):
        super().__init__(decision)
        self.content_review = decision.metadata.get('content_review', False)

    def should_hold_action(self):
        return (
            super().should_hold_action()
            # Only hold rejections for 2nd level approval if...
            # At least one of the version was listed and signed already...
            and self.target_versions.filter(
                channel=amo.CHANNEL_LISTED, file__is_signed=True
            ).exists()
            # And no remaining public listed versions exists (pending rejection
            # don't count) - i.e., going through with the rejection would make
            # the listing go away.
            and not self.remaining_public_listed_versions()
            .exclude(reviewerflags__pending_rejection__isnull=False)
            .exists()
        )

    def remaining_public_listed_versions(self):
        """Return all versions belonging to the add-on that are public and
        listed except for those this action would reject."""
        return self.target.versions.filter(
            channel=amo.CHANNEL_LISTED, file__status=amo.STATUS_APPROVED
        ).exclude(id__in=self.target_versions)

    def notify_stakeholders(self, rejection_type):
        if (
            self.target.promoted_groups(currently_approved=False)
            and self.target_versions.filter(file__is_signed=True).exists()
            and (
                stakeholder_group := Group.objects.filter(
                    name=self.stakeholder_acl_group_name
                ).first()
            )
        ):
            if not (
                recipients := [user.email for user in stakeholder_group.users.all()]
            ):
                # no recipients, nothing to do
                return
            template = loader.get_template(self.stakeholder_template_path)
            versions = list(
                self.target_versions.order_by('id').values_list(
                    'id', 'version', 'channel', named=True
                )
            )
            review_urls = []
            for arg, channel in amo.CHANNEL_CHOICES_LOOKUP.items():
                if any(ver.channel == channel for ver in versions):
                    review_urls += [
                        absolutify(
                            reverse('reviewers.review', args=[arg, self.target.id])
                        )
                    ]
            new_current_version = (
                self.remaining_public_listed_versions().order_by('created').last()
            )
            context_dict = {
                'new_current_version': new_current_version,
                'policy_texts': self.decision.get_policy_texts(),
                'private_notes': self.decision.private_notes,
                'reasoning': self.decision.reasoning,
                'rejection_type': rejection_type,
                'review_urls': ' | '.join(reversed(review_urls)),
                'target_url': self.target.get_absolute_url()
                if self.target.get_url_path()
                else '',
                'type': self.decision.get_target_display(),
                'version_list_listed': ', '.join(
                    vr.version for vr in versions if vr.channel == amo.CHANNEL_LISTED
                ),
                'version_list_unlisted': ', '.join(
                    vr.version for vr in versions if vr.channel == amo.CHANNEL_UNLISTED
                ),
            }
            subject = f'{rejection_type} issued for {self.decision.get_target_name()}'
            message = template.render(context_dict)
            send_mail(subject, message, recipient_list=recipients)

    def prevent_auto_approval(self):
        # For version rejection we only prevent auto-approval in relevant
        # channel(s) until the next manual approval.
        channels = list(
            self.target_versions.values_list('channel', flat=True).distinct()
        )
        channels_to_flags = {
            amo.CHANNEL_LISTED: 'auto_approval_disabled_until_next_approval',
            amo.CHANNEL_UNLISTED: 'auto_approval_disabled_until_next_approval_unlisted',
        }
        auto_approval_flags = {
            channels_to_flags[channel]: True
            for channel in channels
            if channel in channels_to_flags
        }
        if auto_approval_flags:
            AddonReviewerFlags.objects.update_or_create(
                addon=self.target,
                defaults=auto_approval_flags,
            )

    def get_activity_action(self):
        return amo.LOG.REJECT_CONTENT if self.content_review else amo.LOG.REJECT_VERSION

    def process_action(self, release_hold=False):
        if not self.decision.reviewer_user:
            # This action should only be used by reviewer tools, not cinder webhook
            raise NotImplementedError
        if not self.target_versions.exclude(
            file__status=amo.STATUS_DISABLED,
            file__status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
        ).exists():
            return None

        for version in self.target_versions:
            now = datetime.now()
            version.file.update(
                datestatuschanged=now,
                status=amo.STATUS_DISABLED,
                original_status=version.file.status,
                status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
            )
            # (Re)set pending_rejection.
            VersionReviewerFlags.objects.update_or_create(
                version=version,
                defaults={
                    'pending_rejection': None,
                    'pending_rejection_by': None,
                    'pending_content_rejection': None,
                },
            )
            if self.is_human_reviewer():
                # Clear needs human review flags
                self.clear_specific_needs_human_review_flags(version)
                self.set_human_review_date(version)

        self.prevent_auto_approval()
        self.target.update_status()
        self.notify_stakeholders('Rejection')
        return self.log_action(self.get_activity_action())

    def hold_action(self):
        # Even if the action is held, we want to always prevent auto-approval
        # in relevant channels.
        self.prevent_auto_approval()
        # The add-on was still reviewed
        if self.is_human_reviewer():
            for version in self.target_versions:
                # Clear needs human review flags
                self.clear_specific_needs_human_review_flags(version)
                self.set_human_review_date(version)
        return self.log_action(
            amo.LOG.HELD_ACTION_REJECT_CONTENT
            if self.content_review
            else amo.LOG.HELD_ACTION_REJECT_VERSIONS
        )


class ContentActionRejectVersionDelayed(ContentActionRejectVersion):
    description = 'Add-on version(s) will be rejected'
    reporter_template_path = 'abuse/emails/reporter_takedown_addon_delayed.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown_delayed.txt'
    action = DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON

    def __init__(self, decision):
        super().__init__(decision)

        if 'delayed_rejection_date' in self.decision.metadata:
            self.delayed_rejection_date = datetime.fromisoformat(
                self.decision.metadata.get('delayed_rejection_date')
            )
            self.delayed_rejection_days = (
                self.delayed_rejection_date - self.decision.created
            ).days
        else:
            self.delayed_rejection_days = REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
            self.delayed_rejection_date = datetime.now() + timedelta(
                # Add one hour buffer just like reviewer tools form does.
                days=self.delayed_rejection_days,
                hours=1,
            )

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        extra_details = {
            **(extra_details or {}),
            'delayed_rejection_days': self.delayed_rejection_days,
        }
        return super().log_action(
            activity_log_action, *extra_args, extra_details=extra_details
        )

    # should_hold_action as ContentActionRejectVersion

    def get_activity_action(self):
        return (
            amo.LOG.REJECT_CONTENT_DELAYED
            if self.content_review
            else amo.LOG.REJECT_VERSION_DELAYED
        )

    def process_action(self, release_hold=False):
        if not self.decision.reviewer_user:
            # This action should only be used by reviewer tools, not cinder webhook
            raise NotImplementedError

        if release_hold:
            # When releasing a held delayed rejection decision, push the
            # delayed rejection date forward to give developers the same amount
            # of time the reviewer originally intended to give them.
            self.delayed_rejection_date += datetime.now() - self.decision.created

        if (
            not self.target_versions.exclude(
                reviewerflags__pending_rejection=self.delayed_rejection_date,
                reviewerflags__pending_content_rejection=self.content_review,
            )
            .exclude(
                file__status=amo.STATUS_DISABLED, file__original_status=amo.STATUS_NULL
            )
            .exists()
        ):
            return None

        for version in self.target_versions:
            # (Re)set pending_rejection.
            VersionReviewerFlags.objects.update_or_create(
                version=version,
                defaults={
                    'pending_rejection': self.delayed_rejection_date,
                    'pending_rejection_by': self.decision.reviewer_user,
                    'pending_content_rejection': self.content_review,
                },
            )
            if self.is_human_reviewer():
                # Clear needs human review flags
                self.clear_specific_needs_human_review_flags(version)
                self.set_human_review_date(version)
        self.prevent_auto_approval()
        # Developers should be notified again once the deadline is close.
        AddonReviewerFlags.objects.update_or_create(
            addon=self.target,
            defaults={'notified_about_expiring_delayed_rejections': False},
        )
        self.notify_stakeholders(f'{self.delayed_rejection_days} day delayed rejection')
        return self.log_action(self.get_activity_action())

    def hold_action(self):
        # Even if the action is held, we want to always prevent auto-approval
        # in relevant channels.
        self.prevent_auto_approval()
        if self.is_human_reviewer():
            # Clear needs human review flags
            for version in self.target_versions:
                self.clear_specific_needs_human_review_flags(version)
                self.set_human_review_date(version)
        return self.log_action(
            amo.LOG.HELD_ACTION_REJECT_CONTENT_DELAYED
            if self.content_review
            else amo.LOG.HELD_ACTION_REJECT_VERSIONS_DELAYED
        )


class ContentActionRejectVersionFromDelayed(ContentActionRejectVersion):
    action = None  # This should only be used specifically from auto_reject

    def prevent_auto_approval(self):
        # We don't want to change auto-approval for the final rejection
        pass

    def is_human_reviewer(self):
        # When executed, this is always non-human.
        return False

    def get_activity_action(self):
        return (
            amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED
            if self.content_review
            else amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED
        )


class ContentActionBlockAddon(ContentActionDisableAddon):
    description = 'Add-on has been (disabled and) blocked'
    block_type = BlockType.SOFT_BLOCKED
    action = DECISION_ACTIONS.AMO_BLOCK_ADDON

    @property
    def updated_by_user_id(self):
        # When the decision comes from Cinder it doesn't have a reviewer_user, so we use
        # task user to avoid issues with null updated_by in Block save
        return self.decision.reviewer_user_id or settings.TASK_USER_ID

    def should_hold_action(self):
        return bool(
            self.versions_block_will_affect.exists()
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    @classmethod
    def should_be_skipped_by_automation(cls, *, addon, version, **kwargs):
        from olympia.abuse.models import ContentDecision

        # Because this action is very aggressive, we skip it if either:
        # - There been a successful appeal against *any* "negative" decision
        #   on this add-on before
        # - The addon belong to a UsageTier where this action is not available
        usage_tier = addon.get_usage_tier()
        successful_appeal = ContentDecision.objects.filter(
            addon=addon,
            action__in=DECISION_ACTIONS.NON_OFFENDING.values,
            cinder_job__appealed_decisions__action__in=DECISION_ACTIONS.REMOVING.values,
        )
        return successful_appeal or (
            usage_tier and not usage_tier.disable_and_block_action_available
        )

    @property
    def versions_block_will_affect(self):
        """Return all versions that will be blocked by this action."""
        qs = Version.unfiltered.filter(addon=self.target)
        if self.block_type == BlockType.SOFT_BLOCKED:
            # for soft block, we don't want to overwrite a hard block.
            qs = qs.filter(blockversion__id__isnull=True)
        else:
            # otherwise for hard block, we don't need to block already hard blocked.
            qs = qs.exclude(blockversion__block_type=self.block_type)
        return qs.no_transforms().only('pk', 'version', 'file').order_by('-pk')

    def process_action(self, release_hold=False):
        if not self.decision.reviewer_user:
            # For now this action should only be used automatically by scanners and
            # monitoring tasks, not cinder webhook
            raise NotImplementedError
        self.prevent_auto_approval()
        versions = list(self.versions_block_will_affect)
        if versions:
            # Set target_versions before executing the action, since the
            # queryset depends on the file statuses.
            self.decision.target_versions.set(versions)
            disable_too = self.target.status != amo.STATUS_DISABLED
            if disable_too:
                self.target.force_disable(skip_activity_log=True)
            save_versions_to_blocks(
                [self.target.guid],
                BlocklistSubmission(
                    block_type=self.block_type,
                    updated_by_id=self.updated_by_user_id,
                    auto_block_reason=BlockReason.FRAUD_DECEPTIVE,
                    signoff_state=BlocklistSubmission.SIGNOFF_STATES.PUBLISHED,
                    changed_version_ids=[ver.pk for ver in versions],
                    # We're disabling the add-on above, so skip this.
                    disable_addon=False,
                    preserve_block_metadata=True,
                ),
            )
            return (
                self.log_action(
                    amo.LOG.FORCE_DISABLE,
                    extra_details={
                        'is_addon_being_blocked': True,
                        'is_addon_being_disabled': True,
                    },
                )
                if disable_too
                else None
            )
        return None

    def hold_action(self):
        self.prevent_auto_approval()
        if versions := list(self.versions_block_will_affect):
            self.decision.target_versions.set(versions)
            return self.log_action(amo.LOG.HELD_ACTION_FORCE_DISABLE)
        return None


class _ContentActionDelayedBlockAddon(ContentActionBlockAddon):
    # description is dynamic
    action = None  # Has to be redefined in child classes.

    def __init__(self, decision, followup=None):
        super().__init__(decision)
        self.followup = followup
        if not self.delay_days:
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} requires delay_days to be set'
            )

    @property
    def owner_template_path(self):
        # override because we want subclasses to use the same template
        return 'abuse/emails/ContentActionDelayedBlockAddon.txt'

    @classproperty
    def description(cls):
        days = getattr(cls, 'delay_days', 0)
        user_block_label = getattr(cls, 'block_type', BlockType.BLOCKED).user_label
        return f'Add-on versions will be {user_block_label}, after {days} days'

    @classmethod
    def get_existing_blocks_from_decision(cls, decision):
        """Get existing blocks for the decision's target and cache them on the decision.
        We're caching them on the decision to avoid hitting the database multiple times
        when reversing a decision, and because get_blocks_from_guids uses replicas, so
        the data can be stale when we're running in a transaction"""
        if not hasattr(decision, '_existing_blocks'):
            decision._existing_blocks = Block.get_blocks_from_guids(
                [decision.target.guid]
            )
        return decision._existing_blocks

    def process_action(self, release_hold=False):
        versions_qs = self.versions_block_will_affect
        # if this is a followup action, and the primary action is rejecting specific
        # versions, we want to limit the blocking to those versions.
        if self.decision.action in (
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
        ):
            versions_qs = versions_qs.filter(
                id__in=self.decision.target_versions.values_list('id', flat=True)
            )
        versions = list(versions_qs)
        if versions:
            delayed_until = datetime.now() + timedelta(days=self.delay_days)
            submission = BlocklistSubmission(
                auto_block_reason=BlockReason.FRAUD_DECEPTIVE,
                block_type=self.block_type,
                changed_version_ids=[ver.pk for ver in versions],
                disable_addon=False,
                disable_versions=False,
                delayed_until=delayed_until,
                from_followup=self.followup,
                input_guids=self.target.guid,
                preserve_block_metadata=True,
                signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
                updated_by_id=self.updated_by_user_id,
            )
            submission.save()

        return None

    @classmethod
    def reverse_action(cls, original_decision):
        # Note: when the original primary action was ContentDisableAddon, the versions
        # blocked may have been more than target_versions, but we're leaving the other
        # versions blocked.
        guid = original_decision.target.guid
        versions = original_decision.target_versions.all()
        # First unblock any versions that have already been blocked
        already_blocked_version_ids = list(
            versions.filter(blockversion__block_type=cls.block_type).values_list(
                'id', flat=True
            )
        )
        not_blocked_version_ids = set(
            versions.exclude(id__in=already_blocked_version_ids).values_list(
                'id', flat=True
            )
        )
        delete_versions_from_blocks(
            cls.get_existing_blocks_from_decision(original_decision),
            BlocklistSubmission(
                input_guids=guid,
                action=BlocklistSubmission.ACTIONS.DELETE,
                updated_by_id=cls(original_decision, None).updated_by_user_id,
                signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
                changed_version_ids=already_blocked_version_ids,
                preserve_block_metadata=True,
            ),
        )
        # Then cancel any upcoming BlocklistSubmissions that have yet to execute
        upcoming_submissions = BlocklistSubmission.objects.filter(
            input_guids=guid, block_type=cls.block_type
        ).exclude(signoff_state=BlocklistSubmission.SIGNOFF_STATES.PUBLISHED)
        for submission in upcoming_submissions:
            submission_version_ids = set(submission.changed_version_ids)
            if not_blocked_version_ids == submission_version_ids:
                # all versions are in the submission, so we can just delete it.
                submission.delete()
            elif not_blocked_version_ids & submission_version_ids:
                # otherwise, there's some crossover so remove offending versions.
                submission.update(
                    changed_version_ids=list(
                        submission_version_ids - not_blocked_version_ids
                    )
                )

    @classmethod
    def should_be_skipped_by_automation(cls, **kwargs):
        # Follow-up blocks shouldn't be skipped by automation, they are not the
        # main action.
        return False

    def notify_owners(self):
        if not self.followup:
            # TODO support standalone delayed block actions?
            return
        submission = self.followup.blocklistsubmission

        extra_context = {'restricted': self.block_type == BlockType.SOFT_BLOCKED}
        version_numbers = list(
            self.target.versions.filter(
                id__in=submission.changed_version_ids
            ).values_list('version', flat=True)
        )
        extra_context['version_list'] = ', '.join(version_numbers)
        extra_context['followups'] = [
            remaining.description_with_eta
            for remaining in self.decision.followup_actions.exclude(
                Q(id=self.followup.id)  # i.e. this submission
                # and any other submission that has already been published
                | Q(
                    blocklistsubmission__signoff_state=(
                        submission.SIGNOFF_STATES.PUBLISHED
                    )
                ),
            )
        ]
        return super().notify_owners(extra_context=extra_context)


class ContentActionDelayedShortSoftBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.SOFT_BLOCKED
    delay_days = 7
    action = DECISION_ACTIONS.AMO_FU_DELAY_SHORT_SOFT_BLOCK_ADDON


class ContentActionDelayedMidSoftBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.SOFT_BLOCKED
    delay_days = 14
    action = DECISION_ACTIONS.AMO_FU_DELAY_MID_SOFT_BLOCK_ADDON


class ContentActionDelayedLongSoftBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.SOFT_BLOCKED
    delay_days = 28
    action = DECISION_ACTIONS.AMO_FU_DELAY_LONG_SOFT_BLOCK_ADDON


class ContentActionDelayedShortHardBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.BLOCKED
    delay_days = 7
    action = DECISION_ACTIONS.AMO_FU_DELAY_SHORT_HARD_BLOCK_ADDON


class ContentActionDelayedMidHardBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.BLOCKED
    delay_days = 14
    action = DECISION_ACTIONS.AMO_FU_DELAY_MID_HARD_BLOCK_ADDON


class ContentActionDelayedLongHardBlockAddon(_ContentActionDelayedBlockAddon):
    block_type = BlockType.BLOCKED
    delay_days = 28
    action = DECISION_ACTIONS.AMO_FU_DELAY_LONG_HARD_BLOCK_ADDON


class ContentActionRejectListingContent(ContentActionDisableAddon):
    description = 'Add-on listing content has been rejected'
    action = DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT

    @property
    def target_versions(self):
        return self.decision.target_versions.none()

    @classmethod
    def should_be_skipped_by_automation(cls, *, addon, version, **kwargs):
        # Only consider this action in automation if the version is listed.
        return version.channel != amo.CHANNEL_LISTED

    def should_hold_action(self):
        return bool(
            self.target.status not in (amo.STATUS_DISABLED, amo.STATUS_REJECTED)
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    def process_action(self, release_hold=False):
        if self.target.status != amo.STATUS_DISABLED:
            self.target.update(status=amo.STATUS_REJECTED)
            AddonApprovalsCounter.reject_content_for_addon(self.target)
        return self.log_action(amo.LOG.REJECT_LISTING_CONTENT)

    def hold_action(self):
        if self.target.status not in (amo.STATUS_DISABLED, amo.STATUS_REJECTED):
            return self.log_action(amo.LOG.HELD_ACTION_REJECT_LISTING_CONTENT)
        return None


class ContentActionForwardToLegal(ContentActionAddon):
    action = DECISION_ACTIONS.AMO_LEGAL_FORWARD

    def process_action(self, release_hold=False):
        from olympia.abuse.tasks import handle_forward_to_legal_action

        handle_forward_to_legal_action.delay(decision_pk=self.decision.id)
        return self.log_action(amo.LOG.REQUEST_LEGAL)


class ContentActionChangePendingRejectionDate(ContentActionAddon):
    description = 'Add-on pending rejection date has changed'
    action = DECISION_ACTIONS.AMO_CHANGE_PENDING_REJECTION_DATE

    def get_owners(self):
        return self.target.authors.all()


class ContentActionDeleteCollection(ContentAction):
    valid_targets = (Collection,)
    description = 'Collection has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_collection.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'
    action = DECISION_ACTIONS.AMO_DELETE_COLLECTION

    def should_hold_action(self):
        return (
            # Mozilla-owned collection
            not self.target.deleted and self.target.author_id == settings.TASK_USER_ID
        )

    def process_action(self, release_hold=False):
        if not self.target.deleted:
            self.target.delete(clear_slug=False)
            return self.log_action(amo.LOG.COLLECTION_DELETED)
        return None

    def hold_action(self):
        if not self.target.deleted:
            return self.log_action(amo.LOG.HELD_ACTION_COLLECTION_DELETED)
        return None

    def get_owners(self):
        return [self.target.author]


class ContentActionDeleteRating(ContentAction):
    valid_targets = (Rating,)
    description = 'Rating has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_rating.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'
    action = DECISION_ACTIONS.AMO_DELETE_RATING

    def should_hold_action(self):
        # Developer reply in recommended or partner extensions
        return bool(
            not self.target.deleted
            and self.target.reply_to
            and any(
                self.target.addon.promoted_groups(
                    currently_approved=False
                ).high_profile_rating
            )
        )

    def process_action(self, release_hold=False):
        if not self.target.deleted:
            self.target.delete(skip_activity_log=True, clear_flags=False)
            return self.log_action(
                amo.LOG.DELETE_RATING,
                self.target.addon,
                extra_details={
                    'body': str(self.target.body),
                    'addon_id': self.target.addon.pk,
                    'addon_title': str(self.target.addon.name),
                    'is_flagged': self.target.ratingflag_set.exists(),
                },
            )
        return None

    def hold_action(self):
        if not self.target.deleted:
            return self.log_action(amo.LOG.HELD_ACTION_DELETE_RATING, self.target.addon)
        return None

    def get_owners(self):
        return [self.target.user]


class ContentActionTargetAppealApprove(
    AnyTargetMixin, AnyOwnerEmailMixin, ContentAction
):
    description = 'Reported content is within policy, after appeal'

    @property
    def target_versions(self):
        target = self.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            files_qs = File.objects.disabled_that_would_be_renabled_with_addon().filter(
                version__addon=target
            )
            qs = target.versions(manager='unfiltered_for_relations').filter(
                pk__in=files_qs.values_list('version')
            )
        else:
            qs = self.decision.target_versions.all()
        return qs

    @property
    def previous_decisions(self):
        """Queryset with previous decisions made that this action would revert."""
        return self.decision.cinder_job.appealed_decisions.all()

    def process_action(self, release_hold=False):
        from olympia.abuse.models import ContentDecisionFollowupAction

        target = self.target
        log_entry = None
        if isinstance(target, Addon):
            target_versions = (
                self.target_versions.no_transforms()
                .defer('approval_notes')
                .order_by('-pk')
            )
            previous_decision_actions = set(
                self.previous_decisions.values_list('action', flat=True)
            )
            activity_log_action = None

            if {
                DECISION_ACTIONS.AMO_DISABLE_ADDON,
                DECISION_ACTIONS.AMO_BLOCK_ADDON,
                DECISION_ACTIONS.AMO_LEGAL_DISABLE_ADDON,
            } & previous_decision_actions:
                # FIXME: we should also automatically revert the block if the
                # previous decision was AMO_BLOCK_ADDON. (i.e. reverse_action)
                target_versions = list(target_versions)
                if target.status == amo.STATUS_DISABLED:
                    target.force_enable(skip_activity_log=True)
                activity_log_action = amo.LOG.FORCE_ENABLE

            # TODO: rewrite the rest of this function to use per-class reverse_action.
            for prev_decision in self.previous_decisions:
                FollowUpActionClass = CONTENT_ACTION_FROM_DECISION_ACTION[
                    prev_decision.action
                ]
                if hasattr(FollowUpActionClass, 'reverse_action'):
                    FollowUpActionClass.reverse_action(prev_decision)

            if DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON in previous_decision_actions:
                target_versions = list(
                    target_versions.filter(
                        # we only need to unreject disabled versions we rejected
                        file__status=amo.STATUS_DISABLED,
                        file__status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
                    )
                )
                for version in target_versions:
                    version.file.update(
                        datestatuschanged=datetime.now(),
                        status=(
                            # safeguard against original_status not being valid
                            version.file.original_status
                            if version.file.original_status in amo.STATUS_CHOICES_FILE
                            else amo.STATUS_AWAITING_REVIEW
                        ),
                        original_status=amo.STATUS_NULL,
                    )
                target.update_status()
                activity_log_action = amo.LOG.UNREJECT_VERSION
            if (
                DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
                in previous_decision_actions
            ):
                for version in target_versions:
                    VersionReviewerFlags.objects.update_or_create(
                        version=version,
                        defaults={
                            'pending_rejection': None,
                            'pending_rejection_by': None,
                            'pending_content_rejection': None,
                        },
                    )
                activity_log_action = amo.LOG.CLEAR_PENDING_REJECTION
            if (
                DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT in previous_decision_actions
                and target.status == amo.STATUS_REJECTED
            ):
                target_versions = target_versions.none()
                AddonApprovalsCounter.approve_content_for_addon(target)
                # Call update function to correct ihe status
                target.update_status()
                activity_log_action = amo.LOG.APPROVE_REJECTED_LISTING_CONTENT

            if not activity_log_action:
                return

            log_entry = self.log_action(
                activity_log_action,
                *target_versions,
                extra_details={
                    'versions': [version.version for version in target_versions]
                },
            )

        elif isinstance(target, UserProfile) and target.banned:
            UserProfile.objects.filter(pk=target.pk).unban_and_reenable_related_content(
                skip_activity_log=True
            )
            log_entry = self.log_action(amo.LOG.ADMIN_USER_UNBAN)

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_entry = self.log_action(amo.LOG.COLLECTION_UNDELETED)

        elif isinstance(target, Rating) and target.deleted:
            target.undelete(skip_activity_log=True)
            log_entry = self.log_action(
                amo.LOG.UNDELETE_RATING,
                self.target.addon,
                extra_details={
                    'body': str(target.body),
                    'addon_id': target.addon.pk,
                    'addon_title': str(target.addon.name),
                    'is_flagged': target.ratingflag_set.exists(),
                },
            )

        # follow-up actions
        followup_actions = ContentDecisionFollowupAction.objects.filter(
            decision__in=self.previous_decisions, action_date__isnull=False
        )
        for followup_action in followup_actions:
            FollowUpActionClass = CONTENT_ACTION_FROM_DECISION_ACTION[
                followup_action.action
            ]
            FollowUpActionClass.reverse_action(followup_action.decision)

        return log_entry


class ContentActionOverrideApprove(ContentActionTargetAppealApprove):
    description = 'Reported content is within policy, after override'

    @property
    def previous_decisions(self):
        """Queryset with previous decisions made that this action would revert."""
        # If there is no overriden decision this will be an impossible query
        # returning nothing, which is what we want here since this class is
        # specific to overrides actions.
        return self.decision.__class__.objects.filter(pk=self.decision.override_of_id)


class ContentActionApproveListingContent(AnyTargetMixin, ContentAction):
    description = 'Reported content is within policy'
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'
    action = DECISION_ACTIONS.AMO_APPROVE

    def __init__(self, decision):
        super().__init__(decision)
        self.status = self.decision.metadata.get(
            'previous_status',
            self.target.status if isinstance(self.target, Addon) else None,
        )

    def get_owners(self):
        if self.status == amo.STATUS_REJECTED:
            # If we're approving listing content that was rejected, we need to
            # notify the authors.
            return self.target.authors.all()
        return ()

    def process_action(self, release_hold=False):
        if isinstance(self.target, Addon):
            AddonApprovalsCounter.approve_content_for_addon(self.target)
            if self.status == amo.STATUS_REJECTED:
                self.decision.metadata['previous_status'] = self.status
                self.decision.save(update_fields=['metadata'])
                # Call the function to correct it the status
                self.target.update_status()
                log_entry = self.log_action(amo.LOG.APPROVE_REJECTED_LISTING_CONTENT)
            else:
                log_entry = self.log_action(amo.LOG.APPROVE_LISTING_CONTENT)
            return log_entry
        return None


class ContentActionApproveVersion(ContentActionAddon):
    description = (
        'Reported content is within policy, initial decision, approving versions'
    )
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'
    action = DECISION_ACTIONS.AMO_APPROVE_VERSION

    def get_owners(self):
        if (
            self.is_human_reviewer or self.target.type != amo.ADDON_LPAPP
        ) and self.decision.activities.filter(
            # FORCE_ENABLE is logged via the reviewer tools enable_addon action.
            action__in=(amo.LOG.APPROVE_VERSION.id, amo.LOG.FORCE_ENABLE.id)
        ).exists():
            # Don't notify decisions (to cinder or owners) for auto-approved langpacks
            # or if the decision wasn't (freshly) approving any versions.
            return self.target.authors.all()
        else:
            return ()

    def _set_promoted(self, versions):
        group = self.target.promoted_groups(currently_approved=False)
        if group and versions:
            channel = versions[0].channel
            if (channel == amo.CHANNEL_LISTED and any(group.listed_pre_review)) or (
                channel == amo.CHANNEL_UNLISTED and any(group.unlisted_pre_review)
            ):
                # These addons shouldn't be be attempted for auto approval
                # anyway, but double check that the cron job isn't trying to
                # approve it.
                assert self.is_human_reviewer
            for version in versions:
                self.target.approve_for_version(version)

    def process_version(self, version):
        from olympia.reviewers.models import AutoApprovalSummary, NeedsHumanReview

        # Sign addon.
        assert not version.is_blocked

        if version.file.status == amo.STATUS_AWAITING_REVIEW:
            if version.file.is_experiment:
                self.log_action(
                    amo.LOG.EXPERIMENT_SIGNED,
                    version.file,
                    extra_details={'versions': [version.version]},
                    skip_private_notes=True,
                )
            sign_file(version.file)
            if version.channel == amo.CHANNEL_UNLISTED:
                self.log_action(
                    amo.LOG.UNLISTED_SIGNED,
                    version.file,
                    extra_details={'versions': [version.version]},
                    skip_private_notes=True,
                )

            # Save files first, because set_addon checks to make sure there
            # is at least one public file or it won't make the addon public.
            version.file.update(
                datestatuschanged=datetime.now(),
                approval_date=datetime.now(),
                original_status=amo.STATUS_NULL,
                status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
                status=amo.STATUS_APPROVED,
            )
            already_approved = False
        else:
            already_approved = True

        self.set_human_review_date(version)

        if self.is_human_reviewer():
            # Clear pending rejection since we approved that version.
            VersionReviewerFlags.objects.filter(version=version).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )
            try:
                version.autoapprovalsummary.update(confirmed=True)
            except AutoApprovalSummary.DoesNotExist:
                pass
            if version.channel == amo.CHANNEL_UNLISTED:
                self.clear_specific_needs_human_review_flags(version)
        elif (
            version.channel == amo.CHANNEL_UNLISTED
            and version.needshumanreview_set.filter(is_active=True)
            and (delay := self.target.auto_approval_delayed_until_unlisted)
            and delay < datetime.now()
        ):
            # if we're auto-approving because its past the approval delay,
            # flag it.
            NeedsHumanReview.objects.create(
                version=version,
                reason=NeedsHumanReview.REASONS.AUTO_APPROVED_PAST_APPROVAL_DELAY,
            )
        return already_approved

    def process_action(self, release_hold=False):
        if not self.decision.reviewer_user:
            # This action should only be used by reviewer tools, not cinder webhook
            raise NotImplementedError

        if not (versions := list(self.target_versions)):
            return None

        was_public = self.target.is_public()
        already_approved_versions, newly_approved_versions = [], []
        for version in versions:
            if self.process_version(version):
                already_approved_versions.append(version)
            else:
                newly_approved_versions.append(version)

        self._set_promoted(versions)
        if not was_public and newly_approved_versions:
            self.target.update_status()

        channel = versions[0].channel
        if self.is_human_reviewer():
            if channel == amo.CHANNEL_LISTED:
                # No need for a human review anymore in this channel.
                self._clear_all_needs_human_review_flags_in_channel(amo.CHANNEL_LISTED)
                # The counter can be incremented.
                AddonApprovalsCounter.increment_for_addon(addon=self.target)

            # An approval took place so we can reset this.
            AddonReviewerFlags.objects.update_or_create(
                addon=self.target,
                defaults={
                    'auto_approval_disabled_until_next_approval'
                    if channel == amo.CHANNEL_LISTED
                    else 'auto_approval_disabled_until_next_approval_unlisted': False
                },
            )
            self.target.reviewerflags.reload()
        elif channel == amo.CHANNEL_LISTED:
            # Automatic approval, reset the counter.
            AddonApprovalsCounter.reset_for_addon(addon=self.target)

        if newly_approved_versions:
            approve_log = self.log_action(
                amo.LOG.APPROVE_VERSION,
                *newly_approved_versions,
                extra_details={
                    'versions': [version.version for version in newly_approved_versions]
                },
            )
            if not was_public and self.target.is_public():
                log.info('Making %s public' % (self.target))
            else:
                log.info(
                    'Making %s files [%s] public'
                    % (
                        self.target,
                        ', '.join(
                            version.file.file.name
                            for version in newly_approved_versions
                        ),
                    )
                )
        if already_approved_versions:
            confirm_approve_log = self.log_action(
                amo.LOG.CONFIRM_AUTO_APPROVED,
                *already_approved_versions,
                extra_details={
                    'versions': [
                        version.version for version in already_approved_versions
                    ]
                },
                skip_private_notes=bool(newly_approved_versions),
            )
        return (
            (newly_approved_versions and approve_log)
            or (already_approved_versions and confirm_approve_log)
            or None
        )


class ContentActionTargetAppealRemovalAffirmation(
    AnyTargetMixin, AnyOwnerEmailMixin, ContentAction
):
    description = 'Reported content is still offending, after appeal.'

    def process_action(self, release_hold=False):
        previous_decision_actions = (
            self.decision.cinder_job.appealed_decisions.values_list('action', flat=True)
        )
        if (
            isinstance(self.target, Addon)
            and DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT in previous_decision_actions
            and self.target.status == amo.STATUS_REJECTED
        ):
            AddonApprovalsCounter.reject_content_for_addon(self.target)

        return None


class ContentActionIgnore(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Report is invalid, so no action'
    reporter_template_path = 'abuse/emails/reporter_invalid_ignore.txt'
    # no appeal template because no appeals possible
    action = DECISION_ACTIONS.AMO_IGNORE


class ContentActionAlreadyModerated(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Content is already moderated, disabled or deleted, so no action'
    reporter_template_path = 'abuse/emails/reporter_moderated_ignore.txt'
    # no appeal template because no appeals possible
    action = DECISION_ACTIONS.AMO_CLOSED_NO_ACTION


class ContentActionLegalTakedownDisableAddon(ContentActionDisableAddon):
    description = 'Add-on has been disabled, due to legal action'
    action = DECISION_ACTIONS.AMO_LEGAL_DISABLE_ADDON
    # This action should not be used to resolve abuse reports
    reporter_template_path = None
    reporter_appeal_template_path = None

    def get_owners(self):
        # For these actions, legal will handle communication themselves
        return ()


class ContentActionNotImplemented(AnyTargetMixin, NoActionMixin, ContentAction):
    pass


CONTENT_ACTION_FROM_DECISION_ACTION = defaultdict(
    lambda: ContentActionNotImplemented,
    {
        local_.action: local_
        for local_ in vars().values()
        if isclass(local_) and issubclass(local_, ContentAction) and local_.action
    },
)
