from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.decorators import use_primary_db
from olympia.files.utils import lock
from olympia.reviewers.models import (
    clear_reviewing_cache, get_reviewing_cache, set_reviewing_cache
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
                 'actually reject anything.')

    def fetch_addon_candidates(self, *, now):
        """Return a queryset with the Addon instances that have versions that
        should be considered for rejection (deadline before 'now')."""
        return (
            Addon.unfiltered
                 .filter(versions__reviewerflags__pending_rejection__lt=now)
                 .order_by('id').distinct()
        )

    def fetch_version_candidates_for_addon(self, *, addon, now):
        """Return a queryset with the versions that should be considered for
        rejection (deadline before 'now') for a given add-on."""
        return (
            addon.versions(manager='unfiltered_for_relations')
                 .filter(reviewerflags__pending_rejection__lt=now)
                 .order_by('id')
        )

    @transaction.atomic
    def reject_versions(self, *, addon, versions, latest_version):
        """Reject specific versions for an addon."""
        if self.dry_run:
            log.info('Would reject versions %s from add-on %s but this is a '
                     'dry run.', versions, addon)
            return
        helper = ReviewHelper(addon=addon, version=latest_version)
        helper.handler.data = {
            'comments': 'Automatic rejection after grace period ended.',
            'versions': versions,
        }
        helper.handler.reject_multiple_versions()
        VersionReviewerFlags.objects.filter(
            version__in=list(versions)).update(pending_rejection=None)

    def process_addon(self, *, addon, now):
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        if (latest_version and latest_version.is_unreviewed and
                not latest_version.pending_rejection):
            # If latest version is unreviewed and not pending
            # rejection, we want to put the delayed rejection of all
            # versions of this addon on hold until a decision has been
            # made by reviewers on the latest one.
            log.info(
                'Skipping rejections for add-on %s until version %s '
                'has been reviewed', addon.pk, latest_version.pk)
            return
        versions = self.fetch_version_candidates_for_addon(
            addon=addon, now=now)
        if not versions.exists():
            log.info(
                'Somehow no versions to auto-reject for add-on %s', addon.pk)
            return
        locked_by = get_reviewing_cache(addon.pk)
        if locked_by:
            # Don't auto-reject something that has been locked, even by the
            # task user - wait until it's free to avoid any conflicts.
            log.info(
                'Skipping rejections for add-on %s until lock from %s '
                'has expired', addon.pk, locked_by)
            return
            set_reviewing_cache(addon.pk, settings.TASK_USER_ID)
        try:
            self.reject_versions(
                addon=addon, versions=versions, latest_version=latest_version)
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
