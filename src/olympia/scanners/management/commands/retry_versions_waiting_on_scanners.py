from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.constants.scanners import (
    WEBHOOK_MAX_RETRIES,
    WEBHOOK_RETRY_BACKOFF_MAX,
    WEBHOOK_RETRY_INITIAL_DELAY,
)
from olympia.scanners.tasks import wait_for_scanner_results
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.scanners.retry_versions_waiting_on_scanners')

# How long `wait_for_scanner_results` can keep retrying a version: the initial
# countdown plus every retry delay.
MIN_AGE = timedelta(
    seconds=WEBHOOK_RETRY_INITIAL_DELAY
    + sum(
        min(WEBHOOK_RETRY_INITIAL_DELAY * 2**retry, WEBHOOK_RETRY_BACKOFF_MAX)
        for retry in range(WEBHOOK_MAX_RETRIES)
    )
)


class Command(BaseCommand):
    """
    Schedule `wait_for_scanner_results` again for the versions that are not
    auto-approved because they are still waiting on scanner results.

    Only the versions old enough for that task to be over are considered, so
    that we don't end up with two tasks retrying the same version.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help=(
                'Actually schedule the task. Without this flag, the command '
                'only lists the affected versions.'
            ),
        )

    def handle(self, *args, **options):
        force = options['force']

        qs = (
            Version.objects.auto_approvable()
            .filter(
                autoapprovalsummary__is_waiting_on_scanners=True,
                created__lt=datetime.now() - MIN_AGE,
            )
            .order_by('pk')
        )

        self.stdout.write(
            f'Found {qs.count()} version(s) waiting on scanners (force={force}).'
        )

        for version in qs:
            self.stdout.write(f'  - version {version.pk} created {version.created}')

            if not force:
                continue

            wait_for_scanner_results.delay(version_pk=version.pk)
            log.info(
                'Scheduled wait_for_scanner_results again for version %s.', version.pk
            )
