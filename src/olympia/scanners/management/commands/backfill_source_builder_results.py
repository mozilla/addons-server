from django.core.management.base import BaseCommand
from django.urls import reverse

import olympia.core.logger
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.constants.scanners import (
    WEBHOOK,
    WEBHOOK_EVENTS,
    WEBHOOK_ON_SOURCE_CODE_UPLOADED,
)
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import (
    WebhookAddonSerializer,
    WebhookVersionSerializer,
)
from olympia.scanners.tasks import _call_webhook


log = olympia.core.logger.getLogger('z.scanners.backfill_source_builder_results')


class Command(BaseCommand):
    """
    Replay the source-builder webhook call for any ScannerResult tied to the
    on_source_code_uploaded event whose recorded response is `{"message": "Task
    created"}`, which indicates that the tasks have been submitted to the
    service but the build didn't start or the service didn't send the results
    back to AMO.

    This command does not create new scanner results, it simply calls the
    source-builder service again.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help=(
                'Actually call the webhooks. Without this flag, the command '
                'only lists affected scanner results.'
            ),
        )

    def handle(self, *args, **options):
        force = options['force']
        event_name = WEBHOOK_EVENTS[WEBHOOK_ON_SOURCE_CODE_UPLOADED]

        qs = ScannerResult.objects.filter(
            scanner=WEBHOOK,
            webhook_event__event=WEBHOOK_ON_SOURCE_CODE_UPLOADED,
            results__message='Task created',
        ).select_related('webhook_event__webhook', 'version__addon', 'activity_log')

        total = qs.count()
        self.stdout.write(f'Found {total} ScannerResult(s) to replay (force={force}).')

        for scanner_result in qs:
            version = scanner_result.version
            activity_log = scanner_result.activity_log
            webhook = scanner_result.webhook

            if version is None or activity_log is None or webhook is None:
                self.stdout.write(
                    f'  - skip ScannerResult pk={scanner_result.pk}: '
                    f'missing version/activity_log/webhook'
                )
                continue

            self.stdout.write(
                f'  - ScannerResult pk={scanner_result.pk} version={version.pk} '
                f'activity_log={activity_log.pk}'
            )

            if not force:
                continue

            payload = {
                'addon': WebhookAddonSerializer(version.addon).data,
                'version': WebhookVersionSerializer(version).data,
                'activity_log_id': activity_log.id,
                'event': event_name,
                'scanner_result_url': absolutify(
                    reverse('v5:scanner-result-patch', args=[scanner_result.pk])
                ),
            }

            try:
                data = _call_webhook(webhook=webhook, payload=payload)
            except Exception:
                log.exception(
                    'Error replaying source-builder webhook for ScannerResult %s',
                    scanner_result.pk,
                )
                continue

            scanner_result.results = data
            scanner_result.save()
            self.stdout.write(f'    ok -> {data!r}')
