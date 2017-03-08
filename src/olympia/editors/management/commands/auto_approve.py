# -*- coding: utf-8 -*-
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.urlresolvers import reverse

import olympia.core.logger
from olympia import amo
from olympia.editors.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary)
from olympia.editors.views import (
    clear_reviewing_cache, get_reviewing_cache, set_reviewing_cache)
from olympia.versions.models import Version
from olympia.zadmin.models import get_config


log = olympia.core.logger.getLogger('z.editors.auto_approve')


class Command(BaseCommand):
    help = 'Auto-approve add-ons based on predefined criteria'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Do everything except actually approving add-ons.')

    def fetch_candidates(self):
        return (Version.objects.filter(
            addon__type=amo.ADDON_EXTENSION,
            addon__disabled_by_user=False,
            addon__status=amo.STATUS_PUBLIC,
            files__status=amo.STATUS_AWAITING_REVIEW,
            files__is_webextension=True)
            .no_cache().order_by('nomination', 'created').distinct())

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        max_average_daily_users = int(
            get_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS') or 0)
        min_approved_updates = int(
            get_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES') or 0)

        if min_approved_updates <= 0 or max_average_daily_users <= 0:
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

        stats = Counter()
        qs = self.fetch_candidates()
        stats['total'] = len(qs)

        successful_verdict = (
            amo.WOULD_HAVE_BEEN_AUTO_APPROVED if dry_run
            else amo.AUTO_APPROVED)

        for version in qs:
            # Is the addon already locked by a reviewer ?
            if get_reviewing_cache(version.addon.pk):
                stats['locked'] += 1
                continue

            # If admin review or more information was requested, skip this
            # version, let a human handle it.
            if version.addon.admin_review or version.has_info_request:
                stats['flagged'] += 1
                continue

            # Lock the addon for ourselves, no reviewer should touch it.
            set_reviewing_cache(version.addon.pk, settings.TASK_USER_ID)

            try:
                log.info('Processing %s version %s...',
                         unicode(version.addon.name), unicode(version.version))
                summary, info = AutoApprovalSummary.create_summary_for_version(
                    version, max_average_daily_users=max_average_daily_users,
                    min_approved_updates=min_approved_updates,
                    dry_run=dry_run)
                log.info('Auto Approval for %s version %s: %s',
                         unicode(version.addon.name),
                         unicode(version.version),
                         summary.get_verdict_display())
                stats.update({k: int(v) for k, v in info.items()})
                if summary.verdict == successful_verdict:
                    stats['auto_approved'] += 1
                # FIXME: implement auto-approve if verdict is amo.AUTO_APPROVED

            except (AutoApprovalNotEnoughFilesError,
                    AutoApprovalNoValidationResultError):
                log.info(
                    'Version %s was skipped either because it had no '
                    'file or because it had no validation attached.', version)
                stats['error'] += 1
            finally:
                clear_reviewing_cache(version.addon.pk)

        self.log_final_summary(stats, dry_run=dry_run)

    def log_final_summary(self, stats, dry_run=False):
        log.info('There were %d webextensions add-ons in the updates queue.',
                 stats['total'])
        log.info('%d versions were skipped because they were already locked.',
                 stats['locked'])
        log.info('%d versions were skipped because they were flagged for '
                 'admin review or had info requested flag set.',
                 stats['flagged'])
        log.info('%d versions were skipped because they had no files or had '
                 'no validation attached to their files.', stats['error'])
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
        if dry_run:
            log.info('%d versions were marked as would have been approved.',
                     stats['auto_approved'])
        else:
            log.info('%d versions were approved.', stats['auto_approved'])
