import random

from django.conf import settings
from django.template import loader
from django.urls import reverse
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

import waffle

import olympia
from olympia import activity, amo
from olympia.activity import log_create
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import no_jinja_autoescape, send_mail
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


POLICY_DOCUMENT_URL = (
    'https://extensionworkshop.com/documentation/publish/add-on-policies/'
)

log = olympia.core.logger.getLogger('z.abuse')


class CinderAction:
    description = 'Action has been taken'
    valid_targets = []
    reporter_template_path = None
    reporter_appeal_template_path = None

    def __init__(self, cinder_job):
        self.cinder_job = cinder_job
        self.target = self.cinder_job.target
        self.is_third_party_initiated = True  # will not always be true in the future

        if isinstance(self.target, Addon):
            self.addon_version = (
                self.target.current_version
                or self.target.find_latest_version(channel=None, exclude=())
            )

    def process_action(self):
        """This method should return a 2-item tuple:
        - the first item being True (or a truthy value) when an action has taken place
          and the target owners should be notified.
        - the second item is an activity log instance for the action, if available."""
        raise NotImplementedError

    def get_owners(self):
        raise NotImplementedError

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

    def notify_owners(self, *, log_entry_id=None, policy_text=None, extra_context=None):
        owners = self.get_owners()
        if not owners:
            return
        with no_jinja_autoescape():
            template = loader.get_template(self.owner_template_path)
        target_name = self.get_target_name()
        reference_id = f'ref:{self.cinder_job.decision.cinder_id}'
        context_dict = {
            'additional_reasoning': self.cinder_job.decision.notes or '',
            'is_third_party_initiated': self.is_third_party_initiated,
            # Auto-escaping is already disabled above as we're dealing with an
            # email but the target name could have triggered lazy escaping when
            # it was generated so it needs special treatment to avoid it.
            'name': mark_safe(target_name),
            'policy_document_url': POLICY_DOCUMENT_URL,
            'reference_id': reference_id,
            'target': self.target,
            'target_url': absolutify(self.target.get_url_path()),
            'type': self.get_target_type(),
            'SITE_URL': settings.SITE_URL,
            **(extra_context or {}),
        }
        if policy_text is not None:
            context_dict['manual_policy_text'] = policy_text
        else:
            context_dict['policies'] = list(self.cinder_job.decision.policies.all())
        if self.cinder_job.can_be_appealed(is_reporter=False):
            context_dict['appeal_url'] = absolutify(
                reverse(
                    'abuse.appeal_author',
                    kwargs={
                        'decision_cinder_id': self.cinder_job.decision.cinder_id,
                    },
                )
            )

        subject = f'Mozilla Add-ons: {target_name} [{reference_id}]'
        self.send_mail(
            subject,
            template.render(context_dict),
            owners,
            log_entry_id=log_entry_id,
        )

    def send_mail(self, subject, message, recipients, log_entry_id=None):
        send_mail(subject, message, recipient_list=[user.email for user in recipients])

    def notify_reporters(self, reporters=None):
        """Send notification email to reporters.
        reporters: if provided, it is a list of abuse reports that should be notified;
          if not provided, for an appeal all appellants will be notified,
          otherwise all reporters for this job will be notified.
        """
        template = (
            self.reporter_template_path
            if not self.cinder_job.is_appeal
            else self.reporter_appeal_template_path
        )
        if not template:
            return
        with no_jinja_autoescape():
            template = loader.get_template(template)
        reporters = reporters or (
            self.cinder_job.appellants.all()
            if self.cinder_job.is_appeal
            else self.cinder_job.abuse_reports
        )
        for abuse_report in reporters:
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
                    f'ref:{self.cinder_job.decision.cinder_id}/{abuse_report.id}'
                )
                subject = _('Mozilla Add-ons: {} [{}]').format(
                    target_name, reference_id
                )
                context_dict = {
                    # Auto-escaping is already disabled above as we're dealing
                    # with an email but the target name could have triggered
                    # lazy escaping when it was generated so it needs special
                    # treatment to avoid it.
                    'name': mark_safe(target_name),
                    'policy_document_url': POLICY_DOCUMENT_URL,
                    'reference_id': reference_id,
                    'target_url': absolutify(self.target.get_url_path()),
                    'type': self.get_target_type(),
                    'SITE_URL': settings.SITE_URL,
                }
                if self.cinder_job.can_be_appealed(
                    is_reporter=True, abuse_report=abuse_report
                ):
                    context_dict['appeal_url'] = absolutify(
                        reverse(
                            'abuse.appeal_reporter',
                            kwargs={
                                'abuse_report_id': abuse_report.id,
                                'decision_cinder_id': (
                                    self.cinder_job.decision.cinder_id
                                ),
                            },
                        )
                    )
                message = template.render(context_dict)
                send_mail(subject, message, recipient_list=[email_address])


class CinderActionBanUser(CinderAction):
    description = 'Account has been banned'
    valid_targets = [UserProfile]
    reporter_template_path = 'abuse/emails/reporter_takedown_user.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if isinstance(self.target, UserProfile) and not self.target.banned:
            UserProfile.objects.filter(
                pk=self.target.pk
            ).ban_and_disable_related_content()
            return (True, None)
        return (False, None)

    def get_owners(self):
        return [self.target]


class CinderActionDisableAddon(CinderAction):
    description = 'Add-on has been disabled'
    valid_targets = [Addon]
    reporter_template_path = 'abuse/emails/reporter_takedown_addon.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if isinstance(self.target, Addon) and self.target.status != amo.STATUS_DISABLED:
            self.target.force_disable(skip_activity_log=True)
            return (True, log_create(amo.LOG.FORCE_DISABLE, self.target))
        return (False, None)

    def get_owners(self):
        return self.target.authors.all()

    def send_mail(self, subject, message, recipients, *, log_entry_id=None):
        from olympia.activity.utils import send_activity_mail

        """We send addon related via activity mail instead for the integration"""

        if version := getattr(self, 'addon_version', None):
            unique_id = log_entry_id or random.randrange(100000)
            send_activity_mail(
                subject, message, version, recipients, settings.ADDONS_EMAIL, unique_id
            )
        else:
            # we didn't manage to find a version to associate with, we have to fall back
            super().send_mail(subject, message, recipients, log_entry_id=log_entry_id)


class CinderActionRejectVersion(CinderActionDisableAddon):
    description = 'Add-on version(s) have been rejected'

    def process(self):
        # This action should only be used by reviewer tools, not cinder webhook
        raise NotImplementedError


class CinderActionRejectVersionDelayed(CinderActionRejectVersion):
    description = 'Add-on version(s) will be rejected'
    reporter_template_path = 'abuse/emails/reporter_takedown_addon_delayed.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown_delayed.txt'


class CinderActionEscalateAddon(CinderAction):
    valid_targets = [Addon]

    def process_action(self):
        """This will return always return a falsey value because we've not taken any
        action at this point, just flagging for human review."""
        self.flag_for_human_review()
        return (False, None)

    def flag_for_human_review(self):
        from olympia.reviewers.models import NeedsHumanReview

        if not waffle.switch_is_active('enable-cinder-reviewer-tools-integration'):
            log.info(
                'Not adding %s to review queue despite %s because waffle switch is off',
                self.target,
                'escalation',
            )
            return

        if isinstance(self.target, Addon):
            reason = NeedsHumanReview.REASON_CINDER_ESCALATION
            reported_versions = set(
                self.cinder_job.abusereport_set.values_list('addon_version', flat=True)
            )
            version_objs = (
                set(
                    self.target.versions(manager='unfiltered_for_relations')
                    .filter(version__in=reported_versions)
                    .exclude(
                        needshumanreview__reason=reason,
                        needshumanreview__is_active=True,
                    )
                    .no_transforms()
                )
                if reported_versions
                else set()
            )

            nhr_object = None
            # We need custom save() and post_save to be triggered, so we can't
            # optimize this via bulk_create().
            for version in version_objs:
                nhr_object = NeedsHumanReview(
                    version=version, reason=reason, is_active=True
                )
                nhr_object.save(_no_automatic_activity_log=True)
            # If we have more versions specified than versions we flagged, flag latest
            # to be safe. (Either because there was an unknown version, or a None)
            if (
                len(version_objs) != len(reported_versions)
                or len(reported_versions) == 0
            ):
                version_objs = version_objs.union(
                    self.target.set_needs_human_review_on_latest_versions(
                        reason=reason,
                        ignore_reviewed=False,
                        unique_reason=True,
                        skip_activity_log=True,
                    )
                )
            if version_objs:
                version_objs = sorted(version_objs, key=lambda v: v.id)
                # we just need this to exact to do get_reason_display
                nhr_object = nhr_object or NeedsHumanReview(
                    version=version_objs[-1],
                    reason=reason,
                    is_active=True,
                )
                activity.log_create(
                    amo.LOG.NEEDS_HUMAN_REVIEW_CINDER,
                    *version_objs,
                    details={'comments': nhr_object.get_reason_display()},
                )
        return (False, None)

    def get_owners(self):
        # we don't send any emails for escalations
        return ()


class CinderActionDeleteCollection(CinderAction):
    valid_targets = [Collection]
    description = 'Collection has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_collection.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if isinstance(self.target, Collection) and not self.target.deleted:
            self.target.delete(clear_slug=False)
            return (True, log_create(amo.LOG.COLLECTION_DELETED, self.target))
        return (False, None)

    def get_owners(self):
        return [self.target.author]


class CinderActionDeleteRating(CinderAction):
    valid_targets = [Rating]
    description = 'Rating has been deleted'
    reporter_template_path = 'abuse/emails/reporter_takedown_rating.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_takedown.txt'

    def process_action(self):
        if isinstance(self.target, Rating) and not self.target.deleted:
            self.target.delete(clear_flags=False)
            return (True, None)
        return (False, None)

    def get_owners(self):
        return [self.target.user]


class CinderActionTargetAppealApprove(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, after appeal'

    def process_action(self):
        target = self.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable()
            return (True, None)

        elif isinstance(target, UserProfile) and target.banned:
            UserProfile.objects.filter(
                pk=target.pk
            ).unban_and_reenable_related_content()
            return (True, None)

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_create(amo.LOG.COLLECTION_UNDELETED, target)
            return (True, None)

        elif isinstance(target, Rating) and target.deleted:
            target.undelete()
            return (True, None)
        return (False, None)

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


class CinderActionOverrideApprove(CinderActionTargetAppealApprove):
    description = 'Reported content is within policy, after override'


class CinderActionApproveInitialDecision(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, initial decision'
    reporter_template_path = 'abuse/emails/reporter_ignore.txt'
    reporter_appeal_template_path = 'abuse/emails/reporter_appeal_ignore.txt'

    def process_action(self):
        return (False, None)

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


class CinderActionTargetAppealRemovalAffirmation(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is still offending, after appeal.'

    def process_action(self):
        """This returns True because, although we didn't take any action, we
        still want to notify the owner(s)."""
        return (True, None)

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


class CinderActionNotImplemented(CinderAction):
    def process_action(self):
        return (True, None)

    def get_owners(self):
        return ()
