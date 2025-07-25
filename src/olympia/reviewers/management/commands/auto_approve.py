from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.amo.decorators import use_primary_db
from olympia.files.utils import lock
from olympia.lib.crypto.signing import SigningError
from olympia.reviewers.models import (
    AutoApprovalNoValidationResultError,
    AutoApprovalSummary,
    NeedsHumanReview,
    clear_reviewing_cache,
    set_reviewing_cache,
)
from olympia.reviewers.utils import ReviewHelper
from olympia.scanners.models import ScannerResult
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.reviewers.auto_approve')

LOCK_NAME = 'auto-approve'  # Name of the lock() used.


class ApprovalNotAvailableError(Exception):
    pass


class Command(BaseCommand):
    help = 'Auto-approve add-on versions based on predefined criteria'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Fetch version candidates and perform all checks but do not '
            'actually approve anything.',
        )

    def fetch_candidates(self):
        """Return a queryset with the Version ids that should be considered for
        auto approval."""
        return (
            Version.objects.auto_approvable()
            .order_by('created')
            .values_list('id', flat=True)
        )

    @use_primary_db
    def handle(self, *args, **options):
        """Command entry point."""
        self.dry_run = options.get('dry_run', False)

        self.successful_verdict = (
            amo.WOULD_HAVE_BEEN_AUTO_APPROVED if self.dry_run else amo.AUTO_APPROVED
        )

        self.stats = Counter()

        # Get a lock before doing anything, we don't want to have multiple
        # instances of the command running in parallel.
        with lock(settings.TMP_PATH, LOCK_NAME) as lock_attained:
            if lock_attained:
                qs = self.fetch_candidates()
                self.stats['total'] = len(qs)

                for version_id in qs:
                    self.process(version_id)

                self.log_final_summary(self.stats)
            else:
                # We didn't get the lock...
                log.error('auto-approve lock present, aborting.')

    def process(self, version_id):
        """Process a single version by id, figuring out if it should be
        auto-approved and calling the approval code if necessary."""
        version = Version.objects.get(pk=version_id)
        already_locked = AutoApprovalSummary.check_is_locked(version)
        if not already_locked:
            # Lock the addon for ourselves if possible. Even though
            # AutoApprovalSummary.create_summary_for_version() will do
            # call check_is_locked() again later when calculating the verdict,
            # we have to do it now to prevent overwriting an existing lock with
            # our own.
            set_reviewing_cache(version.addon.pk, settings.TASK_USER_ID)

        try:
            with transaction.atomic():
                log.info(
                    'Processing %s version %s...',
                    str(version.addon.name),
                    str(version.version),
                )

                if waffle.switch_is_active('run-action-in-auto-approve'):
                    # We want to execute `run_action()` only once.
                    summary_exists = AutoApprovalSummary.objects.filter(
                        version=version
                    ).exists()
                    if summary_exists:
                        log.info(
                            'Not running run_action() because it has '
                            'already been executed'
                        )
                    else:
                        ScannerResult.run_action(version)

                version.autoapprovalsummary, info = (
                    AutoApprovalSummary.create_summary_for_version(
                        version, dry_run=self.dry_run
                    )
                )
                self.stats.update({k: int(v) for k, v in info.items()})
                if version.autoapprovalsummary.verdict == self.successful_verdict:
                    if version.autoapprovalsummary.verdict == amo.AUTO_APPROVED:
                        self.approve(version)
                    self.stats['auto_approved'] += 1
                    verdict_string = version.autoapprovalsummary.get_verdict_display()
                else:
                    if version.autoapprovalsummary.verdict == amo.NOT_AUTO_APPROVED:
                        self.disapprove(version)
                    verdict_string = '{} ({})'.format(
                        version.autoapprovalsummary.get_verdict_display(),
                        ', '.join(
                            version.autoapprovalsummary.verdict_info_prettifier(info)
                        ),
                    )
                log.info(
                    'Auto Approval for %s version %s: %s',
                    str(version.addon.name),
                    str(version.version),
                    verdict_string,
                )

        # At this point, any exception should have rolled back the transaction,
        # so even if we did create/update an AutoApprovalSummary instance that
        # should have been rolled back. This ensures that, for instance, a
        # signing error doesn't leave the version and its autoapprovalsummary
        # in conflicting states.
        except AutoApprovalNoValidationResultError:
            log.info(
                'Version %s was skipped either because it had no '
                'files or because it had no validation attached.',
                version,
            )
            self.stats['error'] += 1
        except ApprovalNotAvailableError:
            statsd.incr('reviewers.auto_approve.approve.failure')
            log.info(
                'Version %s was skipped because approval action was not available',
                version,
            )
            self.stats['error'] += 1
        except SigningError:
            statsd.incr('reviewers.auto_approve.approve.failure')
            log.info('Version %s was skipped because of a signing error', version)
            self.stats['error'] += 1
        finally:
            # Always clear our own lock no matter what happens (but only ours).
            if not already_locked:
                clear_reviewing_cache(version.addon.pk)

    @statsd.timer('reviewers.auto_approve.approve')
    def approve(self, version):
        """Do the approval itself, caling ReviewHelper to change the status,
        sign the files, send the e-mail, etc."""
        helper = ReviewHelper(
            addon=version.addon,
            version=version,
            human_review=False,
            channel=version.channel,
        )
        approve_action = helper.actions.get('public')
        if not approve_action:
            raise ApprovalNotAvailableError
        if version.channel == amo.CHANNEL_LISTED:
            helper.handler.data = {
                # The comment is not translated on purpose, to behave like
                # regular human approval does.
                'comments': 'This version has been screened and approved for the '
                'public. Keep in mind that other reviewers may look into '
                'this version in the future and determine that it '
                'requires changes or should be taken down.'
                '\r\n\r\nThank you!'
            }
        else:
            helper.handler.data = {'comments': 'automatic validation'}
        approve_action['method']()
        statsd.incr('reviewers.auto_approve.approve.success')

    def disapprove(self, version):
        """Handle a version we are not auto-approving, setting NeedsHumanReview
        if necessary to "transfer" it to the reviewers queue.

        Note that auto-approval might still be re-attempted later still, as
        flags might change etc."""
        verdicts_to_reasons = {
            'is_promoted_prereview': NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP,
            'has_auto_approval_disabled': (
                NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            ),
        }
        # For the specific reasons that cause an add-on to be added to the
        # (human) review queue, we add the corresponding NeedsHumanReview flag
        # if there isn't an active one already - if there is, that means it is
        # already in the queue and there is no need to do it again.
        # Note that we are checking for an active one, because a given version
        # could leave the review queue and re-enter it multiple times.
        for key in verdicts_to_reasons:
            reason = verdicts_to_reasons[key]
            was_not_auto_approved_because_of_that_reason = getattr(
                version.autoapprovalsummary, key
            )
            has_decision_waiting_for_2nd_level_approval = (
                version.contentdecision_set.awaiting_action().exists()
            )
            already_has_same_active_nhr = version.needshumanreview_set.filter(
                reason=reason, is_active=True
            ).exists()
            if (
                was_not_auto_approved_because_of_that_reason
                and not version.pending_rejection
                and not has_decision_waiting_for_2nd_level_approval
                and not already_has_same_active_nhr
            ):
                NeedsHumanReview.objects.create(version=version, reason=reason)

    def log_final_summary(self, stats):
        """Log a summary of what happened."""
        log.info('There were %d webextensions add-ons in the queue.', stats['total'])
        if stats['error']:
            log.info(
                '%d versions were skipped because they had no files or had '
                'no validation attached to their files, or signing failed on '
                'their files.',
                stats['error'],
            )
        if self.dry_run:
            log.info(
                '%d versions were marked as would have been approved.',
                stats['auto_approved'],
            )
        else:
            log.info('%d versions were approved.', stats['auto_approved'])
