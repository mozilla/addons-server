import random
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import loader
from django.urls import reverse
from django.utils import translation
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
from olympia.blocklist.models import BlocklistSubmission, BlockType
from olympia.blocklist.utils import save_versions_to_blocks
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.permissions import ADDONS_HIGH_IMPACT_APPROVE
from olympia.files.models import File
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

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        user_kw = (
            {'user': self.decision.reviewer_user} if self.decision.reviewer_user else {}
        )
        if self.decision.private_notes:
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

        context_dict = {
            'is_listing_disabled': getattr(self.target, 'status', None)
            == amo.STATUS_REJECTED,
            'is_third_party_initiated': self.decision.is_third_party_initiated,
            # It's a plain-text email so we're safe to include comments without escaping
            # them - we don't want ', etc, rendered as html entities.
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


class ContentActionDisableAddon(ContentAction):
    description = 'Add-on has been disabled'
    valid_targets = (Addon,)
    reporter_template_path = 'abuse/emails/reporter_takedown_addon.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def should_hold_action(self):
        return bool(
            self.target.status != amo.STATUS_DISABLED
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        from olympia.activity.models import AttachmentLog
        from olympia.reviewers.models import ReviewActionReason

        human_review = bool(
            (user := self.decision.reviewer_user) and user.id != settings.TASK_USER_ID
        )
        extra_details = {'human_review': human_review} | (extra_details or {})
        if (
            target_versions := self.target_versions.no_transforms()
            .only('pk', 'version')
            .order_by('-pk')
        ):
            extra_args = (*target_versions, *extra_args)
            extra_details['versions'] = [version.version for version in target_versions]
        # While we still have ReviewActionReason in addition to ContentPolicy, re-add
        # any instances from earlier activity logs (e.g. held action)
        reasons = ReviewActionReason.objects.filter(
            reviewactionreasonlog__activity_log__contentdecision__id=self.decision.id
        )
        activity_log = super().log_action(
            activity_log_action, *extra_args, *reasons, extra_details=extra_details
        )
        # move any attachments to latest decision
        if attachment := AttachmentLog.objects.filter(
            activity_log__contentdecision__id=self.decision.id
        ).first():
            attachment.update(activity_log=activity_log)
            activity_log.attachmentlog = attachment  # update fk
        return activity_log

    @property
    def target_versions(self):
        return self.decision.target_versions.all()

    @property
    def versions_force_disable_will_affect(self):
        return (
            Version.objects.all()
            .filter(addon=self.target)
            .exclude(file__status=amo.STATUS_DISABLED)
            .no_transforms()
            .only('pk', 'version')
            .order_by('-pk')
        )

    def process_action(self, release_hold=False):
        if self.target.status != amo.STATUS_DISABLED:
            # Set target_versions before executing the action, since the
            # queryset depends on the file statuses.
            self.decision.target_versions.set(self.versions_force_disable_will_affect)
            self.target.force_disable(skip_activity_log=True)
            return self.log_action(amo.LOG.FORCE_DISABLE)
        return None

    def hold_action(self):
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

        self.target.update_status()
        self.notify_stakeholders('Rejection')
        return self.log_action(
            amo.LOG.REJECT_CONTENT if self.content_review else amo.LOG.REJECT_VERSION
        )

    def hold_action(self):
        return self.log_action(
            amo.LOG.HELD_ACTION_REJECT_CONTENT
            if self.content_review
            else amo.LOG.HELD_ACTION_REJECT_VERSIONS
        )


class ContentActionRejectVersionDelayed(ContentActionRejectVersion):
    description = 'Add-on version(s) will be rejected'
    reporter_template_path = 'abuse/emails/reporter_takedown_addon_delayed.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown_delayed.txt'

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
            # Will fail later if we try to use it to log/process the action,
            # but allows us to at least instantiate the class and use other
            # methods.
            self.delayed_rejection_date = self.delayed_rejection_days = None

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        extra_details = {
            **(extra_details or {}),
            'delayed_rejection_days': self.delayed_rejection_days,
        }
        return super().log_action(
            activity_log_action, *extra_args, extra_details=extra_details
        )

    # should_hold_action as ContentActionRejectVersion

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
        # Developers should be notified again once the deadline is close.
        AddonReviewerFlags.objects.update_or_create(
            addon=self.target,
            defaults={'notified_about_expiring_delayed_rejections': False},
        )
        self.notify_stakeholders(f'{self.delayed_rejection_days} day delayed rejection')
        return self.log_action(
            amo.LOG.REJECT_CONTENT_DELAYED
            if self.content_review
            else amo.LOG.REJECT_VERSION_DELAYED
        )

    def hold_action(self):
        return self.log_action(
            amo.LOG.HELD_ACTION_REJECT_CONTENT_DELAYED
            if self.content_review
            else amo.LOG.HELD_ACTION_REJECT_VERSIONS_DELAYED
        )


class ContentActionBlockAddon(ContentActionDisableAddon):
    description = 'Add-on has been (disabled and) blocked'

    def should_hold_action(self):
        return bool(
            self.versions_block_will_affect.exists()
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    @property
    def versions_block_will_affect(self):
        """Return all versions that will be blocked by this action."""
        return (
            Version.unfiltered.filter(addon=self.target, blockversion__id__isnull=True)
            .no_transforms()
            .only('pk', 'version')
            .order_by('-pk')
        )

    def process_action(self, release_hold=False):
        if not self.decision.reviewer_user:
            # For now this action should only be used automatically by scanners and
            # monitoring tasks, not cinder webhook
            raise NotImplementedError
        versions = list(self.versions_block_will_affect)
        if versions:
            # Set target_versions before executing the action, since the
            # queryset depends on the file statuses.
            self.decision.target_versions.set(versions)
            disable_too = self.target.status != amo.STATUS_DISABLED
            if disable_too:
                self.target.force_disable(skip_activity_log=True)
            reason = (
                "This add-on violates Mozilla's add-on policies by including or using "
                'deceptive, misleading, or fraudulent activity or functionality'
            )
            save_versions_to_blocks(
                [self.target.guid],
                BlocklistSubmission(
                    block_type=BlockType.SOFT_BLOCKED,
                    updated_by=self.decision.reviewer_user,
                    reason=reason,
                    signoff_state=BlocklistSubmission.SIGNOFF_STATES.PUBLISHED,
                    changed_version_ids=[ver.pk for ver in versions],
                    # We're disabling the add-on above, so skip this.
                    disable_addon=False,
                ),
                overwrite_block_metadata=False,
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
        if versions := list(self.versions_block_will_affect):
            self.decision.target_versions.set(versions)
            return self.log_action(amo.LOG.HELD_ACTION_FORCE_DISABLE)
        return None


class ContentActionRejectListingContent(ContentActionDisableAddon):
    description = 'Add-on listing content has been rejected'

    @property
    def target_versions(self):
        return self.decision.target_versions.none()

    def should_hold_action(self):
        return bool(
            self.target.status not in (amo.STATUS_DISABLED, amo.STATUS_REJECTED)
            # is a high profile add-on
            and any(self.target.promoted_groups(currently_approved=False).high_profile)
        )

    def process_action(self, release_hold=False):
        if self.target.status not in (amo.STATUS_DISABLED, amo.STATUS_REJECTED):
            self.target.update(status=amo.STATUS_REJECTED)
            AddonApprovalsCounter.objects.update_or_create(
                addon=self.target, defaults={'last_content_review_pass': False}
            )
        return self.log_action(amo.LOG.REJECT_LISTING_CONTENT)

    def hold_action(self):
        if self.target.status not in (amo.STATUS_DISABLED, amo.STATUS_REJECTED):
            return self.log_action(amo.LOG.HELD_ACTION_REJECT_LISTING_CONTENT)
        return None


class ContentActionForwardToLegal(ContentAction):
    valid_targets = (Addon,)

    def process_action(self, release_hold=False):
        from olympia.abuse.tasks import handle_forward_to_legal_action

        handle_forward_to_legal_action.delay(decision_pk=self.decision.id)
        return self.log_action(amo.LOG.REQUEST_LEGAL)


class ContentActionChangePendingRejectionDate(ContentAction):
    description = 'Add-on pending rejection date has changed'
    valid_targets = (Addon,)

    def get_owners(self):
        return self.target.authors.all()


class ContentActionDeleteCollection(ContentAction):
    valid_targets = (Collection,)
    description = 'Collection has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_collection.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

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
        return self.decision.cinder_job.appealed_decisions

    def process_action(self, release_hold=False):
        target = self.target
        log_entry = None
        if isinstance(target, Addon):
            target_versions = (
                self.target_versions.no_transforms()
                .only('pk', 'version')
                .order_by('-pk')
            )
            previous_decision_actions = self.previous_decisions.values_list(
                'action', flat=True
            )
            activity_log_action = None

            if (
                DECISION_ACTIONS.AMO_DISABLE_ADDON in previous_decision_actions
                or DECISION_ACTIONS.AMO_BLOCK_ADDON in previous_decision_actions
            ):
                # FIXME: we should also automatically revert the block if the
                # previous decision was AMO_BLOCK_ADDON.
                target_versions = list(target_versions)
                if target.status == amo.STATUS_DISABLED:
                    target.force_enable(skip_activity_log=True)
                activity_log_action = amo.LOG.FORCE_ENABLE
            if DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON in previous_decision_actions:
                target_versions = list(
                    target_versions.filter(
                        # we only need to unreject disabled versions we rejected
                        file__status=amo.STATUS_DISABLED,
                        file__status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
                    ).only('pk', 'version', 'file')
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
                AddonApprovalsCounter.objects.update_or_create(
                    addon=target,
                    defaults={
                        'last_content_review': datetime.now(),
                        'last_content_review_pass': True,
                    },
                )
                # Call the function to correct it the status
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
            AddonApprovalsCounter.objects.update_or_create(
                addon=self.target,
                defaults={
                    'last_content_review': datetime.now(),
                    'last_content_review_pass': True,
                },
            )
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


class ContentActionApproveInitialDecision(
    AnyTargetMixin, NoActionMixin, AnyOwnerEmailMixin, ContentAction
):
    description = (
        'Reported content is within policy, initial decision, approving versions'
    )
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'


class ContentActionTargetAppealRemovalAffirmation(
    AnyTargetMixin, NoActionMixin, AnyOwnerEmailMixin, ContentAction
):
    description = 'Reported content is still offending, after appeal.'


class ContentActionIgnore(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Report is invalid, so no action'
    reporter_template_path = 'abuse/emails/reporter_invalid_ignore.txt'
    # no appeal template because no appeals possible


class ContentActionAlreadyModerated(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Content is already moderated, disabled or deleted, so no action'
    reporter_template_path = 'abuse/emails/reporter_moderated_ignore.txt'
    # no appeal template because no appeals possible


class ContentActionNotImplemented(AnyTargetMixin, NoActionMixin, ContentAction):
    pass


CONTENT_ACTION_FROM_DECISION_ACTION = defaultdict(
    lambda: ContentActionNotImplemented,
    {
        DECISION_ACTIONS.AMO_BAN_USER: ContentActionBanUser,
        DECISION_ACTIONS.AMO_DISABLE_ADDON: ContentActionDisableAddon,
        DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON: ContentActionRejectVersion,
        DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON: (
            ContentActionRejectVersionDelayed
        ),
        DECISION_ACTIONS.AMO_BLOCK_ADDON: ContentActionBlockAddon,
        DECISION_ACTIONS.AMO_DELETE_COLLECTION: ContentActionDeleteCollection,
        DECISION_ACTIONS.AMO_DELETE_RATING: ContentActionDeleteRating,
        DECISION_ACTIONS.AMO_APPROVE: ContentActionApproveListingContent,
        DECISION_ACTIONS.AMO_APPROVE_VERSION: ContentActionApproveInitialDecision,
        DECISION_ACTIONS.AMO_IGNORE: ContentActionIgnore,
        DECISION_ACTIONS.AMO_CLOSED_NO_ACTION: ContentActionAlreadyModerated,
        DECISION_ACTIONS.AMO_LEGAL_FORWARD: ContentActionForwardToLegal,
        DECISION_ACTIONS.AMO_CHANGE_PENDING_REJECTION_DATE: (
            ContentActionChangePendingRejectionDate
        ),
        DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT: ContentActionRejectListingContent,
    },
)
