from io import StringIO
from unittest import mock

from django.core.management import call_command

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.constants.scanners import (
    WEBHOOK,
    WEBHOOK_DURING_VALIDATION,
    WEBHOOK_ON_SOURCE_CODE_UPLOADED,
)
from olympia.scanners.models import (
    ScannerResult,
    ScannerWebhook,
    ScannerWebhookEvent,
)


class TestBackfillSourceBuilderResults(TestCase):
    COMMAND = 'backfill_source_builder_results'

    def setUp(self):
        super().setUp()
        self.webhook = ScannerWebhook.objects.create(
            name='source-builder',
            url='https://example.org/',
            api_key='some-api-key',
            is_active=True,
        )
        self.webhook_event = ScannerWebhookEvent.objects.create(
            webhook=self.webhook, event=WEBHOOK_ON_SOURCE_CODE_UPLOADED
        )

    def _make_stuck_result(
        self,
        *,
        results=None,
        webhook_event=None,
        with_version=True,
        with_activity_log=True,
    ):
        if results is None:
            results = {'message': 'Task created'}

        version = None
        if with_version:
            addon = addon_factory()
            version = version_factory(addon=addon)

        activity_log = None
        if with_activity_log:
            activity_log = ActivityLog.objects.create(
                amo.LOG.SOURCE_CODE_UPLOADED,
                version.addon if version else addon_factory(),
                user=user_factory(),
            )

        return ScannerResult.objects.create(
            scanner=WEBHOOK,
            webhook_event=webhook_event or self.webhook_event,
            version=version,
            activity_log=activity_log,
            results=results,
        )

    def _run(self, *args):
        stdout = StringIO()
        call_command(self.COMMAND, *args, stdout=stdout)
        return stdout.getvalue()

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_no_matching_results(self, _call_webhook_mock):
        output = self._run()

        assert 'Found 0 ScannerResult(s) to replay' in output
        assert not _call_webhook_mock.called

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_lists_without_force(self, _call_webhook_mock):
        sr = self._make_stuck_result()

        output = self._run()

        assert 'Found 1 ScannerResult(s) to replay (force=False)' in output
        assert f'ScannerResult pk={sr.pk}' in output
        assert not _call_webhook_mock.called
        # Existing row is left untouched.
        sr.reload()
        assert sr.results == {'message': 'Task created'}

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_force_calls_webhook_and_updates_existing_row(self, _call_webhook_mock):
        returned_data = {'message': 'done', 'something': 'else'}
        _call_webhook_mock.return_value = returned_data
        sr = self._make_stuck_result()

        self._run('--force')

        assert _call_webhook_mock.call_count == 1
        kwargs = _call_webhook_mock.call_args.kwargs
        assert kwargs['webhook'] == self.webhook

        payload = kwargs['payload']
        assert payload['event'] == 'on_source_code_uploaded'
        assert payload['activity_log_id'] == sr.activity_log.pk
        # The existing ScannerResult pk is reused so the service PATCHes back
        # onto the same row.
        assert payload['scanner_result_url'] == (
            f'http://testserver/api/v5/scanner/results/{sr.pk}/'
        )
        assert payload['version']['id'] == sr.version.pk
        assert payload['addon']['id'] == sr.version.addon.pk

        # No new ScannerResult was created — the existing row is reused.
        assert ScannerResult.objects.count() == 1
        sr.reload()
        assert sr.results == returned_data

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_ignores_non_matching_rows(self, _call_webhook_mock):
        # Different message.
        self._make_stuck_result(results={'message': 'something else'})
        # Different event.
        other_event = ScannerWebhookEvent.objects.create(
            webhook=self.webhook, event=WEBHOOK_DURING_VALIDATION
        )
        self._make_stuck_result(webhook_event=other_event)

        self._run('--force')

        assert not _call_webhook_mock.called

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_skips_rows_missing_relations(self, _call_webhook_mock):
        sr_no_version = self._make_stuck_result(with_version=False)
        sr_no_activity = self._make_stuck_result(with_activity_log=False)

        output = self._run('--force')

        assert f'skip ScannerResult pk={sr_no_version.pk}' in output
        assert f'skip ScannerResult pk={sr_no_activity.pk}' in output
        assert not _call_webhook_mock.called

    @mock.patch(
        'olympia.scanners.management.commands.'
        'backfill_source_builder_results._call_webhook'
    )
    def test_continues_on_webhook_exception(self, _call_webhook_mock):
        _call_webhook_mock.side_effect = [
            RuntimeError('boom'),
            {'message': 'done'},
        ]
        sr1 = self._make_stuck_result()
        sr2 = self._make_stuck_result()

        self._run('--force')

        assert _call_webhook_mock.call_count == 2
        sr1.reload()
        sr2.reload()
        # First one wasn't updated because the call raised.
        assert sr1.results == {'message': 'Task created'}
        assert sr2.results == {'message': 'done'}
