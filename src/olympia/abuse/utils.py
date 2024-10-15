import random

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
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


POLICY_DOCUMENT_URL = (
    'https://extensionworkshop.com/documentation/publish/add-on-policies/'
)

log = olympia.core.logger.getLogger('z.abuse')


class CinderAction:
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
                self.target.current_version
                or self.target.find_latest_version(channel=None, exclude=())
            )

        if not isinstance(self.target, self.valid_targets):
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} needs a target that is one of '
                f'{self.valid_targets}'
            )

    def log_action(self, activity_log_action):
        return log_create(
            activity_log_action,
            self.target,
            *(self.decision.policies.all()),
            details={
                'comments': self.decision.notes,
                'cinder_action': self.decision.action,
            },
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

    def get_target_name(self):
        return str(
            _('"{}" for {}').format(self.target, self.target.addon.name)
            if isinstance(self.target, Rating)
            else getattr(self.target, 'name', self.target)
        )

    def get_target_type(self):
        match self.target:
            case target if isinstance(target, Addon):
                return target.get_type_display()
            case target if isinstance(target, UserProfile):
                return _('User profile')
            case target if isinstance(target, Collection):
                return _('Collection')
            case target if isinstance(target, Rating):
                return _('Rating')
            case target:
                return target.__class__.__name__

    @property
    def owner_template_path(self):
        return f'abuse/emails/{self.__class__.__name__}.txt'

    def notify_owners(self, *, log_entry_id=None, extra_context=None):
        from olympia.activity.utils import send_activity_mail

        owners = self.get_owners()
        if not owners:
            return
        template = loader.get_template(self.owner_template_path)
        target_name = self.get_target_name()
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
            'type': self.get_target_type(),
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
                target_name = self.get_target_name()
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
                    'type': self.get_target_type(),
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


class CinderActionBanUser(CinderAction):
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
                    addon.promoted_group().high_profile
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


class CinderActionDisableAddon(CinderAction):
    description = 'Add-on has been disabled'
    valid_targets = (Addon,)
    reporter_template_path = 'abuse/emails/reporter_takedown_addon.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if self.target.status != amo.STATUS_DISABLED:
            self.target.force_disable(skip_activity_log=True)
            return log_create(amo.LOG.FORCE_DISABLE, self.target)
        return None

    def get_owners(self):
        return self.target.authors.all()


class CinderActionRejectVersion(CinderActionDisableAddon):
    description = 'Add-on version(s) have been rejected'

    def process_action(self):
        # This action should only be used by reviewer tools, not cinder webhook
        raise NotImplementedError


class CinderActionRejectVersionDelayed(CinderActionRejectVersion):
    description = 'Add-on version(s) will be rejected'
    reporter_template_path = 'abuse/emails/reporter_takedown_addon_delayed.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown_delayed.txt'


class CinderActionEscalateAddon(CinderAction):
    valid_targets = (Addon,)

    def process_action(self):
        from olympia.abuse.tasks import handle_escalate_action

        handle_escalate_action.delay(job_pk=self.decision.cinder_job.pk)


class CinderActionDeleteCollection(CinderAction):
    valid_targets = (Collection,)
    description = 'Collection has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_collection.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if not self.target.deleted:
            self.target.delete(clear_slug=False)
            return log_create(amo.LOG.COLLECTION_DELETED, self.target)
        return None

    def get_owners(self):
        return [self.target.author]


class CinderActionDeleteRating(CinderAction):
    valid_targets = (Rating,)
    description = 'Rating has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_rating.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if not self.target.deleted:
            self.target.delete(clear_flags=False)
        return None

    def get_owners(self):
        return [self.target.user]


class CinderActionTargetAppealApprove(AnyTargetMixin, AnyOwnerEmailMixin, CinderAction):
    description = 'Reported content is within policy, after appeal'

    def process_action(self):
        target = self.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable()

        elif isinstance(target, UserProfile) and target.banned:
            UserProfile.objects.filter(
                pk=target.pk
            ).unban_and_reenable_related_content()

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_create(amo.LOG.COLLECTION_UNDELETED, target)

        elif isinstance(target, Rating) and target.deleted:
            target.undelete()
        return None


class CinderActionOverrideApprove(CinderActionTargetAppealApprove):
    description = 'Reported content is within policy, after override'


class CinderActionApproveNoAction(AnyTargetMixin, NoActionMixin, CinderAction):
    description = 'Reported content is within policy, initial decision, so no action'
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'


class CinderActionApproveInitialDecision(
    AnyTargetMixin, NoActionMixin, AnyOwnerEmailMixin, CinderAction
):
    description = (
        'Reported content is within policy, initial decision, approving versions'
    )
    reporter_template_path = 'abuse/emails/reporter_content_approve.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_approve.txt'


class CinderActionTargetAppealRemovalAffirmation(
    AnyTargetMixin, NoActionMixin, AnyOwnerEmailMixin, CinderAction
):
    description = 'Reported content is still offending, after appeal.'


class CinderActionIgnore(AnyTargetMixin, NoActionMixin, CinderAction):
    description = 'Report is invalid, so no action'
    reporter_template_path = 'abuse/emails/reporter_invalid_ignore.txt'
    # no appeal template because no appeals possible


class CinderActionAlreadyRemoved(AnyTargetMixin, NoActionMixin, CinderAction):
    description = 'Content is already disabled or deleted, so no action'
    reporter_template_path = 'abuse/emails/reporter_disabled_ignore.txt'
    # no appeal template because no appeals possible


class CinderActionNotImplemented(NoActionMixin, CinderAction):
    pass
