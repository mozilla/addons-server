import random
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import loader
from django.urls import reverse
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

import waffle

import olympia
from olympia import amo
from olympia.activity import log_create
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail
from olympia.bandwagon.models import Collection
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import VersionReviewerFlags


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

    def __init__(self, decision):
        self.decision = decision
        self.target = self.decision.target

        if isinstance(self.target, Addon):
            self.addon_version = (
                (decision.id and decision.target_versions.order_by('-id').first())
                or self.target.current_version
                or self.target.find_latest_version(channel=None, exclude=())
            )

        if not isinstance(self.target, self.valid_targets):
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} needs a target that is one of '
                f'{self.valid_targets}'
            )

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        return log_create(
            activity_log_action,
            self.target,
            self.decision,
            *(self.decision.policies.all()),
            *extra_args,
            **(
                {'user': self.decision.reviewer_user}
                if self.decision.reviewer_user
                else {}
            ),
            details={'comments': self.decision.notes, **(extra_details or {})},
        )

    def should_hold_action(self):
        """This should return false if the action should be processed immediately,
        without further checks, and true if it should be held for further review."""
        return False

    def process_action(self):
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
            'is_third_party_initiated': self.decision.is_third_party_initiated,
            # It's a plain-text email so we're safe to include comments without escaping
            # them - we don't want ', etc, rendered as html entities.
            'manual_reasoning_text': mark_safe(self.decision.notes or ''),
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
        if 'policies' not in context_dict:
            context_dict['policies'] = self.decision.policies.all()
        if self.decision.can_be_appealed(is_reporter=False) and (
            self.decision.is_third_party_initiated
            or waffle.switch_is_active('dsa-appeals-review')
        ):
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
                        self.decision.notes or ''
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


class AnyTargetMixin:
    valid_targets = (Addon, UserProfile, Collection, Rating)


class NoActionMixin:
    def process_action(self):
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
                    addon.promoted_group(currently_approved=False).high_profile
                    for addon in self.target.addons.all()
                )
            )
        )

    def process_action(self):
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
            and self.target.promoted_group(currently_approved=False).high_profile
        )

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        from olympia.reviewers.models import ReviewActionReason

        human_review = bool(
            (user := self.decision.reviewer_user) and user.id != settings.TASK_USER_ID
        )
        extra_details = {'human_review': human_review} | (extra_details or {})
        if self.addon_version:
            extra_args = (self.addon_version, *extra_args)
            extra_details['version'] = self.addon_version.version
        # While we still have ReviewActionReason in addition to ContentPolicy, re-add
        # any instances from earlier activity logs (e.g. held action)
        reasons = ReviewActionReason.objects.filter(
            reviewactionreasonlog__activity_log__contentdecision__id=self.decision.id
        )
        return super().log_action(
            activity_log_action, *extra_args, *reasons, extra_details=extra_details
        )

    def process_action(self):
        if self.target.status != amo.STATUS_DISABLED:
            self.target.force_disable(skip_activity_log=True)
            return self.log_action(amo.LOG.FORCE_DISABLE)
        return None

    def hold_action(self):
        if self.target.status != amo.STATUS_DISABLED:
            return self.log_action(amo.LOG.HELD_ACTION_FORCE_DISABLE)
        return None

    def get_owners(self):
        return self.target.authors.all()


class ContentActionRejectVersion(ContentActionDisableAddon):
    description = 'Add-on version(s) have been rejected'

    def __init__(self, decision):
        super().__init__(decision)
        self.content_review = decision.metadata.get('content_review', False)

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        # include target versions. addon_version will be included already
        versions = tuple(
            self.decision.target_versions.exclude(id=self.addon_version.id)
        )
        return super().log_action(
            activity_log_action, *extra_args, *versions, extra_details=extra_details
        )

    # should_hold_action as ContentActionDisableAddon

    def process_action(self):
        if not self.decision.reviewer_user:
            # This action should only be used by reviewer tools, not cinder webhook
            raise NotImplementedError
        for version in self.decision.target_versions.all():
            version.file.update(
                datestatuschanged=datetime.now(),
                status=amo.STATUS_DISABLED,
                original_status=amo.STATUS_NULL,
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
        self.days = int(self.decision.metadata.get('delayed_rejection_days', 0))

    def log_action(self, activity_log_action, *extra_args, extra_details=None):
        extra_details = {**(extra_details or {}), 'delayed_rejection_days': self.days}
        return super().log_action(
            activity_log_action, *extra_args, extra_details=extra_details
        )

    # should_hold_action as ContentActionDisableAddon

    def process_action(self):
        if not self.decision.reviewer_user:
            # This action should only be used by reviewer tools, not cinder webhook
            raise NotImplementedError
        pending_rejection_deadline = datetime.now() + timedelta(days=self.days)

        for version in self.decision.target_versions.all():
            # (Re)set pending_rejection.
            VersionReviewerFlags.objects.update_or_create(
                version=version,
                defaults={
                    'pending_rejection': pending_rejection_deadline,
                    'pending_rejection_by': self.decision.reviewer_user,
                    'pending_content_rejection': self.content_review,
                },
            )
        # Developers should be notified again once the deadline is close.
        AddonReviewerFlags.objects.update_or_create(
            addon=self.target,
            defaults={'notified_about_expiring_delayed_rejections': False},
        )
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


class ContentActionForwardToReviewers(ContentAction):
    valid_targets = (Addon,)

    def process_action(self):
        from olympia.abuse.tasks import handle_escalate_action

        handle_escalate_action.delay(job_pk=self.decision.originating_job.pk)


class ContentActionForwardToLegal(ContentAction):
    valid_targets = (Addon,)

    def process_action(self):
        from olympia.abuse.tasks import handle_forward_to_legal_action

        handle_forward_to_legal_action.delay(decision_pk=self.decision.id)
        return self.log_action(amo.LOG.REQUEST_LEGAL)


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

    def process_action(self):
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
            and self.target.addon.promoted_group(
                currently_approved=False
            ).high_profile_rating
        )

    def process_action(self):
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

    def process_action(self):
        target = self.target
        log_entry = None
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable(skip_activity_log=True)
            log_entry = self.log_action(amo.LOG.FORCE_ENABLE)

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
                    'body': str(self.target.body),
                    'addon_id': self.target.addon.pk,
                    'addon_title': str(self.target.addon.name),
                    'is_flagged': self.target.ratingflag_set.exists(),
                },
            )

        return log_entry


class ContentActionOverrideApprove(ContentActionTargetAppealApprove):
    description = 'Reported content is within policy, after override'


class ContentActionApproveNoAction(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Reported content is within policy, initial decision, so no action'
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'


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


class ContentActionAlreadyRemoved(AnyTargetMixin, NoActionMixin, ContentAction):
    description = 'Content is already disabled or deleted, so no action'
    reporter_template_path = 'abuse/emails/reporter_disabled_ignore.txt'
    # no appeal template because no appeals possible


class ContentActionNotImplemented(NoActionMixin, ContentAction):
    pass
