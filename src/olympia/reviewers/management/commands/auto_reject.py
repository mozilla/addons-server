from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import waffle

import olympia.core.logger
from olympia import amo
from olympia.abuse.actions import ContentActionRejectVersionFromDelayed
from olympia.abuse.models import (
    CinderJob,
    CinderPolicy,
    ContentDecision,
    ContentDecisionFollowupAction,
)
from olympia.abuse.tasks import report_decision_to_cinder_and_notify
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.decorators import use_primary_db
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.files.utils import lock
from olympia.reviewers.models import (
    clear_reviewing_cache,
    get_reviewing_cache,
    set_reviewing_cache,
)
from olympia.reviewers.utils import ReviewHelper
from olympia.versions.models import VersionReviewerFlags


log = olympia.core.logger.getLogger('z.reviewers.auto_reject')

LOCK_NAME = 'auto-reject'  # Name of the lock() used.


class Command(BaseCommand):
    help = 'Auto-reject add-on versions pending rejection'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Fetch version candidates and perform all checks but do not '
            'actually reject anything.',
        )

    def fetch_addon_candidates(self, *, now):
        """Return a queryset with the Addon instances that have versions that
        should be considered for rejection (deadline before 'now')."""
        return (
            Addon.unfiltered.filter(versions__reviewerflags__pending_rejection__lt=now)
            .order_by('id')
            .distinct()
        )

    def fetch_version_candidates_for_addon(self, *, addon, now):
        """Return a queryset with the versions that should be considered for
        rejection (deadline before 'now') for a given add-on."""
        return (
            addon.versions(manager='unfiltered_for_relations')
            .filter(reviewerflags__pending_rejection__lt=now)
            .select_related('reviewerflags')
            .order_by('id')
        )

    def reject_versions(self, *, addon, versions, latest_version):
        """Reject specific versions, either by calling ReviewHelper or by creating a
        ContentDecision and calling its execute_action() method."""
        if self.dry_run:
            log.info(
                'Would reject versions %s from add-on %s but this is a dry run.',
                versions,
                addon,
            )
            return
        if waffle.switch_is_active('enable-policy-review-selection'):
            self.reject_versions_with_action_class(addon=addon, versions=versions)
        else:
            self.reject_versions_with_review_helper(
                addon=addon, versions=versions, latest_version=latest_version
            )

    def reject_versions_with_review_helper(self, *, addon, versions, latest_version):
        """Reject specific versions for an addon, via reviwer tools ReviewHelper."""
        helper = ReviewHelper(
            addon=addon, version=latest_version, human_review=False, channel=None
        )
        relevant_activity_logs = ActivityLog.objects.for_versions(versions).filter(
            action__in=(
                amo.LOG.REJECT_CONTENT_DELAYED.id,
                amo.LOG.REJECT_VERSION_DELAYED.id,
            )
        )
        log_details = getattr(relevant_activity_logs.first(), 'details', {})
        cinder_jobs = CinderJob.objects.filter(
            pending_rejections__version__in=versions
        ).distinct()
        helper.handler.data = {
            'comments': log_details.get('comments', ''),
            'cinder_jobs_to_resolve': cinder_jobs,
            'cinder_policies': CinderPolicy.objects.filter(
                cinderpolicylog__activity_log__in=relevant_activity_logs
            ).distinct(),
            'versions': versions,
        }
        helper.handler.review_action = {
            'enforcement_actions': [
                DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            ]
        }
        helper.handler.auto_reject_multiple_versions()
        VersionReviewerFlags.objects.filter(version__in=list(versions)).update(
            pending_rejection=None,
            pending_rejection_by=None,
            pending_content_rejection=None,
        )

    def reject_versions_with_action_class(self, *, addon, versions):
        """Reject specific versions for an addon, via reviwer tools ReviewHelper."""
        previous_decisions = ContentDecision.objects.filter(
            action_date__isnull=False,
            overridden_by__isnull=True,
            target_versions__in=versions,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
        ).distinct()

        for previous_decision in previous_decisions:
            if not versions or not previous_decision.target_versions.exists():
                log.info(
                    'Skipping rejection for add-on %s since there are no versions '
                    'to reject or no previous decision to override.',
                    addon.pk,
                )
                continue
            decision_versions = previous_decision.target_versions.filter(
                id__in=versions
            )
            new_decision = ContentDecision.objects.create(
                cinder_job=previous_decision.cinder_job,
                override_of=previous_decision,
                addon=addon,
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                action_date=datetime.now(),
                reasoning=previous_decision.reasoning,
                reviewer_user_id=previous_decision.reviewer_user_id,
                metadata=previous_decision.metadata,
            )
            new_decision.policies.set(previous_decision.policies.all())
            new_decision.target_versions.set(decision_versions)
            # We copy the follow-up actions, but we don't need to re-execute them.
            ContentDecisionFollowupAction.objects.bulk_create(
                ContentDecisionFollowupAction(decision=new_decision, action=action)
                for action in previous_decision.followup_actions.all()
            )
            action_helper = ContentActionRejectVersionFromDelayed(decision=new_decision)
            action_helper.process_action()

            if new_decision.cinder_job:
                new_decision.cinder_job.pending_rejections.clear()

            report_decision_to_cinder_and_notify.delay(decision_id=new_decision.id)

    def process_addon(self, *, addon, now):
        try:
            with transaction.atomic():
                latest_version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
                if (
                    latest_version
                    and latest_version.is_unreviewed
                    and not latest_version.pending_rejection
                ):
                    # If latest version is unreviewed and not pending
                    # rejection, we want to put the delayed rejection of all
                    # versions of this addon on hold until a decision has been
                    # made by reviewers on the latest one.
                    log.info(
                        'Skipping rejections for add-on %s until version %s '
                        'has been reviewed',
                        addon.pk,
                        latest_version.pk,
                    )
                    return
                versions = self.fetch_version_candidates_for_addon(addon=addon, now=now)
                if not versions.exists():
                    log.info(
                        'Somehow no versions to auto-reject for add-on %s', addon.pk
                    )
                    return
                locked_by = get_reviewing_cache(addon.pk)
                if locked_by:
                    # Don't auto-reject something that has been locked, even by the
                    # task user - wait until it's free to avoid any conflicts.
                    log.info(
                        'Skipping rejections for add-on %s until lock from user %s '
                        'has expired',
                        addon.pk,
                        locked_by,
                    )
                    return
                set_reviewing_cache(addon.pk, settings.TASK_USER_ID)
                self.reject_versions(
                    addon=addon, versions=versions, latest_version=latest_version
                )
        finally:
            # Always clear our lock no matter what happens.
            clear_reviewing_cache(addon.pk)

    @use_primary_db
    def handle(self, *args, **kwargs):
        """Command entry point."""
        self.dry_run = kwargs.get('dry_run', False)
        now = datetime.now()

        # Get a lock before doing anything, we don't want to have multiple
        # instances of the command running in parallel.
        with lock(settings.TMP_PATH, LOCK_NAME) as lock_attained:
            if not lock_attained:
                log.error('auto-reject lock present, aborting')
                return
            addons = self.fetch_addon_candidates(now=now)
            for addon in addons:
                self.process_addon(addon=addon, now=now)
