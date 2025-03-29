from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia import amo
from olympia.abuse.actions import ContentActionRejectVersionDelayed
from olympia.abuse.models import CinderJob, ContentDecision
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.constants.abuse import DECISION_ACTIONS


log = olympia.core.logger.getLogger(
    'z.reviewers.send_pending_rejection_last_warning_notifications'
)


class Command(BaseCommand):
    help = (
        'Notify developers about add-ons with versions pending rejection '
        'close to deadline.'
    )

    EXPIRING_PERIOD_DAYS = 1

    def handle(self, *args, **kwargs):
        """Command entry point."""
        in_the_near_future = datetime.now() + timedelta(days=self.EXPIRING_PERIOD_DAYS)
        addons = self.fetch_addon_candidates(deadline=in_the_near_future)
        for addon in addons:
            self.process_addon(addon=addon, deadline=in_the_near_future)

    def fetch_addon_candidates(self, *, deadline):
        """Return a queryset with the public Add-ons that have versions that
        are close to being rejected, excluding those for which we already sent
        that last warning notification."""
        exclusions = {
            'reviewerflags__notified_about_expiring_delayed_rejections': True,
        }
        filters = {
            'versions__reviewerflags__pending_rejection__lt': deadline,
        }
        return (
            Addon.objects.public()
            .filter(**filters)
            .exclude(**exclusions)
            .order_by('id')
            .distinct()
        )

    def fetch_version_candidates_for_addon(self, *, addon, deadline):
        """Return a queryset with the versions that are close to being
        rejected for a given add-on and that are worth notifying the
        developers about (public/awaiting review)."""
        return (
            addon.versions.filter(file__status__in=amo.VALID_FILE_STATUSES)
            .filter(reviewerflags__pending_rejection__lt=deadline)
            .order_by('id')
        )

    def notify_developers(self, *, addon, versions):
        # Fetch the activity log to retrieve the comments to include in the
        # email. There is no global one, so we just take the latest we can find
        # for those versions with a delayed rejection action.
        relevant_activity_log = (
            ActivityLog.objects.for_versions(versions)
            .filter(
                action__in=(
                    amo.LOG.REJECT_CONTENT_DELAYED.id,
                    amo.LOG.REJECT_VERSION_DELAYED.id,
                )
            )
            .last()
        )
        if (
            not relevant_activity_log
            or not relevant_activity_log.details
            or not relevant_activity_log.details.get('comments')
        ):
            log.info(
                'Skipping notification about versions pending rejections for '
                'add-on %s since there is no activity log or comments.',
                addon.pk,
            )
            return
        log.info('Sending email for %s' % addon)
        cinder_job = (
            CinderJob.objects.filter(pending_rejections__version__in=versions)
            .distinct()
            .first()
        )
        # We just need the decision to send an accurate email
        decision = (
            cinder_job.decision.final
            if cinder_job and cinder_job.decision
            # Fake a decision if there isn't a job
            else ContentDecision(
                addon=addon,
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            )
        )
        decision.notes = relevant_activity_log.details.get('comments', '')
        action_helper = ContentActionRejectVersionDelayed(decision)
        action_helper.notify_owners(
            log_entry_id=relevant_activity_log.id,
            extra_context={
                'delayed_rejection_days': self.EXPIRING_PERIOD_DAYS,
                'version_list': ', '.join(str(v.version) for v in versions),
                # Because we expand the reason/policy text into notes in the reviewer
                # tools, we don't want to duplicate it as policies too.
                'policy_texts': (),
            },
        )

        # Note that we did this so that we don't notify developers of this
        # add-on again until next rejection.
        AddonReviewerFlags.objects.update_or_create(
            addon=addon,
            defaults={'notified_about_expiring_delayed_rejections': True},
        )

    def process_addon(self, *, addon, deadline):
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        if latest_version and not latest_version.pending_rejection:
            # If the latest version for this add-on in this channel is not
            # pending rejection, we don't need to warn the developer: they have
            # already done something to fix the problem, or the versions we're
            # going to reject are just old ones that don't really affect the
            # listing. Even if somehow the latest version is still awaiting
            # review the developer likely can't do much at this point.
            log.info(
                'Skipping notification about versions pending rejections for '
                'add-on %s since there is a more recent version %s not '
                'pending rejection',
                addon.pk,
                latest_version.pk,
            )
            return
        versions = self.fetch_version_candidates_for_addon(
            addon=addon, deadline=deadline
        )
        if not versions.exists():
            log.info(
                'No versions pending rejection to notify developers about for '
                'add-on %s, skipping',
                addon.pk,
            )
            return
        self.notify_developers(addon=addon, versions=versions)
