from olympia import amo
from olympia.activity import log_create
from olympia.addons.models import Addon
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

    def notify_targets(self, targets):
        # TODO: notify target
        pass

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
            self.notify_targets([self.target])


class CinderActionDisableAddon(CinderAction):
    description = 'Add-on has been disabled'
    valid_targets = [Addon]

    def process(self):
        if isinstance(self.target, Addon) and self.target.status != amo.STATUS_DISABLED:
            self.target.force_disable()
            self.notify_reporters()
            self.notify_targets(self.target.authors.all())


class CinderActionEscalateAddon(CinderAction):
    valid_targets = [Addon]

    def process(self):
        from olympia.reviewers.models import NeedsHumanReview

        if isinstance(self.target, Addon):
            reason = NeedsHumanReview.REASON_CINDER_ESCALATION
            reported_versions = set(
                self.cinder_job.abusereport_set.values_list('addon_version', flat=True)
            )
            version_objs = set(
                self.target.versions(manager='unfiltered_for_relations')
                .filter(version__in=reported_versions)
                .no_transforms()
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
            self.notify_targets([self.target.author])


class CinderActionDeleteRating(CinderAction):
    valid_targets = [Rating]
    description = 'Rating has been deleted'

    def process(self):
        if isinstance(self.target, Rating) and not self.target.deleted:
            self.target.delete(clear_flags=False)
            self.notify_reporters()
            self.notify_targets([self.target.user])


class CinderActionApproveAppealOverride(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, after appeal/override'

    def process(self):
        self.notify_reporters()
        target = self.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable()
            self.notify_targets(target.authors.all())

        elif isinstance(target, UserProfile) and target.banned:
            UserProfile.objects.filter(
                pk=target.pk
            ).unban_and_reenable_related_content()
            self.notify_targets([target])

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_create(amo.LOG.COLLECTION_UNDELETED, target)
            self.notify_targets([target.author])

        elif isinstance(target, Rating) and target.deleted:
            target.undelete()
            self.notify_targets([target.user])


class CinderActionApproveInitialDecision(CinderAction):
    valid_targets = [Addon, UserProfile, Collection, Rating]
    description = 'Reported content is within policy, initial decision'

    def process(self):
        self.notify_reporters()
        # If it's an initial decision approve there is nothing else to do


class CinderActionNotImplemented(CinderAction):
    def process(self):
        pass
