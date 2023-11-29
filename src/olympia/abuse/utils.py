import random

from django.conf import settings
from django.template import loader
from django.urls import reverse

from olympia import amo
from olympia.activity import log_create
from olympia.addons.models import Addon
from olympia.amo.utils import send_mail
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class CinderAction:
    description = 'Action has been taken'
    valid_targets = []

    def __init__(self, cinder_job):
        self.cinder_job = cinder_job
        self.target = self.cinder_job.target

    def process(self):
        raise NotImplementedError

    def notify_owners(self, owners):
        abuse_report = self.cinder_job.abusereport_set.first()
        if not abuse_report:
            return
        name = (
            f'"{abuse_report.target}" for {abuse_report.target.addon.name}'
            if isinstance(abuse_report.target, Rating)
            else getattr(abuse_report.target, 'name', abuse_report.target)
        )
        context_dict = {
            'target': abuse_report.target,
            'name': name,
            'target_url': abuse_report.target.get_url_path(),
            'reasons': [policy.text for policy in self.cinder_job.policies.all()],
            'appeal_url': reverse(
                'abuse.appeal',
                kwargs={
                    'abuse_report_id': abuse_report.id,
                    'decision_id': self.cinder_job.decision_id,
                },
            ),
            'SITE_URL': settings.SITE_URL,
        }

        subject = f'Mozilla Add-ons: {name}'
        template = loader.get_template(f'abuse/emails/{self.__class__.__name__}.txt')
        self.send_mail(
            subject,
            template.render(context_dict),
            owners,
        )

    def send_mail(self, subject, message, recipients):
        send_mail(subject, message, recipient_list=[user.email for user in recipients])

    def notify_reporters(self):
        for abuse_report in self.cinder_job.abusereport_set.all():
            if abuse_report.reporter or abuse_report.reporter_email:
                # TODO: notify reporter
                pass


class CinderActionBanUser(CinderAction):
    description = 'Account has been banned'
    valid_targets = [UserProfile]

    def process(self):
        if isinstance(self.target, UserProfile) and not self.target.banned:
            UserProfile.objects.filter(
                pk=self.target.pk
            ).ban_and_disable_related_content()
            self.notify_reporters()
            self.notify_owners([self.target])


class CinderActionDisableAddon(CinderAction):
    description = 'Add-on has been disabled'
    valid_targets = [Addon]

    def process(self):
        if isinstance(self.target, Addon) and self.target.status != amo.STATUS_DISABLED:
            self.addon_version = (
                self.target.current_version
                or self.target.find_latest_version(channel=None, exclude=())
            )
            self.target.force_disable(skip_activity_log=True)
            self.log_entry = log_create(amo.LOG.FORCE_DISABLE, self.target)
            self.notify_reporters()
            self.notify_owners(self.target.authors.all())

    def send_mail(self, subject, message, recipients):
        from olympia.activity.utils import send_activity_mail

        """We send addon related via activity mail instead for the integration"""

        if version := self.addon_version:
            unique_id = (
                self.log_entry.id if self.log_entry else random.randrange(100000)
            )
            send_activity_mail(
                subject, message, version, recipients, settings.ADDONS_EMAIL, unique_id
            )
        else:
            # we didn't manage to find a version to associate with, we have to fall back
            super().send_mail(subject, message, recipients)


class CinderActionEscalateAddon(CinderAction):
    valid_targets = [Addon]

    def process(self):
        from olympia.reviewers.models import NeedsHumanReview

        if isinstance(self.target, Addon):
            reason = NeedsHumanReview.REASON_CINDER_ESCALATION
            reported_versions = set(
                self.cinder_job.abusereport_set.values_list('addon_version', flat=True)
            )
            version_objs = (
                set(
                    self.target.versions(manager='unfiltered_for_relations')
                    .filter(version__in=reported_versions)
                    .no_transforms()
                )
                if reported_versions
                else set()
            )
            # We need custom save() and post_save to be triggered, so we can't
            # optimize this via bulk_create().
            for version in version_objs:
                NeedsHumanReview.objects.create(
                    version=version, reason=reason, is_active=True
                )
            # If we have more versions specified than versions we flagged, flag latest
            # to be safe. (Either because there was an unknown version, or a None)
            if (
                len(version_objs) != len(reported_versions)
                or len(reported_versions) == 0
            ):
                self.target.set_needs_human_review_on_latest_versions(
                    reason=reason, ignore_reviewed=False, unique_reason=True
                )


class CinderActionDeleteCollection(CinderAction):
    valid_targets = [Collection]
    description = 'Collection has been deleted'

    def process(self):
        if isinstance(self.target, Collection) and not self.target.deleted:
            log_create(amo.LOG.COLLECTION_DELETED, self.target)
            self.target.delete(clear_slug=False)
            self.notify_reporters()
            self.notify_owners([self.target.author])


class CinderActionDeleteRating(CinderAction):
    valid_targets = [Rating]
    description = 'Rating has been deleted'

    def process(self):
        if isinstance(self.target, Rating) and not self.target.deleted:
            self.target.delete(clear_flags=False)
            self.notify_reporters()
            self.notify_owners([self.target.user])


class CinderActionApproveAppealOverride(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, after appeal/override'

    def process(self):
        self.notify_reporters()
        target = self.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable()
            self.notify_owners(target.authors.all())

        elif isinstance(target, UserProfile) and target.banned:
            UserProfile.objects.filter(
                pk=target.pk
            ).unban_and_reenable_related_content()
            self.notify_owners([target])

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_create(amo.LOG.COLLECTION_UNDELETED, target)
            self.notify_owners([target.author])

        elif isinstance(target, Rating) and target.deleted:
            target.undelete()
            self.notify_owners([target.user])


class CinderActionApproveInitialDecision(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, initial decision'

    def process(self):
        self.notify_reporters()
        # If it's an initial decision approve there is nothing else to do


class CinderActionNotImplemented(CinderAction):
    def process(self):
        pass
