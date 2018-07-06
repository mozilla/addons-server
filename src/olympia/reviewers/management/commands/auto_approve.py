# -*- coding: utf-8 -*-
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.files.utils import atomic_lock
from olympia.reviewers.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, clear_reviewing_cache, set_reviewing_cache)
from olympia.reviewers.utils import ReviewHelper
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.reviewers.auto_approve')

LOCK_NAME = 'auto-approve'  # Name of the atomic_lock() used.


class Command(BaseCommand):
    help = 'Auto-approve add-ons based on predefined criteria'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Do everything except actually approving add-ons.')

    def fetch_candidates(self):
        """Return a queryset with the Version instances that should be
        considered for auto approval."""
        return (Version.objects.filter(
            addon__type__in=(amo.ADDON_EXTENSION, amo.ADDON_LPAPP),
            addon__disabled_by_user=False,
            addon__status__in=(amo.STATUS_PUBLIC, amo.STATUS_NOMINATED),
            files__status=amo.STATUS_AWAITING_REVIEW,
            files__is_webextension=True)
            .order_by('nomination', 'created').distinct())

    def handle(self, *args, **options):
        """Command entry point."""
        self.dry_run = options.get('dry_run', False)

        self.successful_verdict = (
            amo.WOULD_HAVE_BEEN_AUTO_APPROVED if self.dry_run
            else amo.AUTO_APPROVED)

        self.stats = Counter()

        # Get a lock before doing anything, we don't want to have multiple
        # instances of the command running in parallel.
        lock = atomic_lock(settings.TMP_PATH, LOCK_NAME, lifetime=15 * 60)
        with lock as lock_attained:
            if lock_attained:
                qs = self.fetch_candidates()
                self.stats['total'] = len(qs)

                for version in qs:
                    self.process(version)

                self.log_final_summary(self.stats)
            else:
                # We didn't get the lock...
                log.error('auto-approve lock present, aborting.')

    @transaction.atomic
    def process(self, version):
        """Process a single version, figuring out if it should be auto-approved
        and calling the approval code if necessary."""
        already_locked = AutoApprovalSummary.check_is_locked(version)
        if not already_locked:
            # Lock the addon for ourselves if possible. Even though
            # AutoApprovalSummary.create_summary_for_version() will do
            # call check_is_locked() again later when calculating the verdict,
            # we have to do it now to prevent overwriting an existing lock with
            # our own.
            set_reviewing_cache(version.addon.pk, settings.TASK_USER_ID)
        try:
            log.info('Processing %s version %s...',
                     unicode(version.addon.name), unicode(version.version))
            summary, info = AutoApprovalSummary.create_summary_for_version(
                version, dry_run=self.dry_run)
            log.info('Auto Approval for %s version %s: %s',
                     unicode(version.addon.name),
                     unicode(version.version),
                     summary.get_verdict_display())
            self.stats.update({k: int(v) for k, v in info.items()})
            if summary.verdict == self.successful_verdict:
                self.stats['auto_approved'] += 1
                if summary.verdict == amo.AUTO_APPROVED:
                    self.approve(version)

        except (AutoApprovalNotEnoughFilesError,
                AutoApprovalNoValidationResultError):
            log.info(
                'Version %s was skipped either because it had no '
                'file or because it had no validation attached.', version)
            self.stats['error'] += 1
        finally:
            # Always clear our own lock no matter what happens (but only ours).
            if not already_locked:
                clear_reviewing_cache(version.addon.pk)

    def approve(self, version):
        """Do the approval itself, caling ReviewHelper to change the status,
        sign the files, send the e-mail, etc."""
        # Note: this should automatically use the TASK_USER_ID user.
        helper = ReviewHelper(addon=version.addon, version=version)
        helper.handler.data = {
            # The comment is not translated on purpose, to behave like regular
            # human approval does.
            'comments': u'This version has been screened and approved for the '
                        u'public. Keep in mind that other reviewers may look '
                        u'into this version in the future and determine that '
                        u'it requires changes or should be taken down. In '
                        u'that case, you will be notified again with details '
                        u'and next steps.'
                        u'\r\n\r\nThank you!'
        }
        helper.handler.process_public()
        statsd.incr('reviewers.auto_approve.approve')

    def log_final_summary(self, stats):
        """Log a summary of what happened."""
        log.info('There were %d webextensions add-ons in the queue.',
                 stats['total'])
        if stats['error']:
            log.info(
                '%d versions were skipped because they had no files or had '
                'no validation attached to their files.', stats['error'])
        if self.dry_run:
            log.info('%d versions were marked as would have been approved.',
                     stats['auto_approved'])
        else:
            log.info('%d versions were approved.', stats['auto_approved'])
