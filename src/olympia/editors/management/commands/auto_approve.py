# -*- coding: utf-8 -*-
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.urlresolvers import reverse
from django.db import transaction

import waffle

import olympia.core.logger
from olympia import amo
from olympia.editors.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, clear_reviewing_cache, set_reviewing_cache)
from olympia.editors.utils import ReviewHelper
from olympia.files.utils import atomic_lock
from olympia.versions.models import Version
from olympia.zadmin.models import get_config


log = olympia.core.logger.getLogger('z.editors.auto_approve')

LOCK_NAME = 'auto-approve'  # Name of the atomic_lock() used.


class Command(BaseCommand):
    help = 'Auto-approve add-ons based on predefined criteria'
    post_review = False

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
        if self.post_review:
            addon_statuses = (amo.STATUS_PUBLIC, amo.STATUS_NOMINATED)
        else:
            addon_statuses = (amo.STATUS_PUBLIC,)
        return (Version.objects.filter(
            addon__type__in=(amo.ADDON_EXTENSION, amo.ADDON_LPAPP),
            addon__disabled_by_user=False,
            addon__status__in=addon_statuses,
            files__status=amo.STATUS_AWAITING_REVIEW,
            files__is_webextension=True)
            .no_cache().order_by('nomination', 'created').distinct())

    def handle(self, *args, **options):
        """Command entry point."""
        self.post_review = waffle.switch_is_active('post-review')
        self.dry_run = options.get('dry_run', False)
        self.max_average_daily_users = int(
            get_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS') or 0)
        self.min_approved_updates = int(
            get_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES') or 0)

        if self.min_approved_updates <= 0 or self.max_average_daily_users <= 0:
            # Auto approval are shut down if one of those values is not present
            # or <= 0.
            url = '%s%s' % (
                settings.SITE_URL,
                reverse('admin:zadmin_config_changelist'))
            raise CommandError(
                'Auto-approvals are deactivated because either '
                'AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS or '
                'AUTO_APPROVAL_MIN_APPROVED_UPDATES have not been '
                'set or were set to 0. Use the admin tools Config model to '
                'set them by going to %s.' % url)

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
                version, max_average_daily_users=self.max_average_daily_users,
                min_approved_updates=self.min_approved_updates,
                dry_run=self.dry_run,
                post_review=waffle.switch_is_active('post-review'))
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
            'comments': u'This version has been approved for the public.'
                        u'\r\n\r\nThank you!'
        }
        helper.handler.process_public()

    def log_final_summary(self, stats):
        """Log a summary of what happened."""
        log.info('There were %d webextensions add-ons in the queue.',
                 stats['total'])
        if stats['error']:
            log.info(
                '%d versions were skipped because they had no files or had '
                'no validation attached to their files.', stats['error'])
        if not self.post_review:
            log.info('%d versions were already locked by a reviewer.',
                     stats['is_locked'])
            log.info('%d versions were flagged for admin review',
                     stats['is_under_admin_review'])
            log.info('%d versions had a pending info request',
                     stats['has_info_request'])
            log.info('%d versions belonged to an add-on with too many daily '
                     'active users.', stats['too_many_average_daily_users'])
            log.info('%d versions did not have enough approved updates.',
                     stats['too_few_approved_updates'])
            log.info('%d versions used a custom CSP.',
                     stats['uses_custom_csp'])
            log.info('%d versions used nativeMessaging permission.',
                     stats['uses_native_messaging'])
            log.info('%d versions used a content script for all URLs.',
                     stats['uses_content_script_for_all_urls'])
        if self.dry_run:
            log.info('%d versions were marked as would have been approved.',
                     stats['auto_approved'])
        else:
            log.info('%d versions were approved.', stats['auto_approved'])
