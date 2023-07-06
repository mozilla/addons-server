from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import requests

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    MAD,
    NEW,
    RUNNING,
    SCHEDULED,
    YARA,
)
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.scanners.models import (
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
)
from olympia.scanners.tasks import (
    _run_yara,
    call_mad_api,
    mark_yara_query_rule_as_completed_or_aborted,
    run_customs,
    run_scanner,
    run_yara,
    run_yara_query_rule,
    run_yara_query_rule_on_versions_chunk,
)
from olympia.versions.models import Version


class TestRunScanner(UploadMixin, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = {FAKE_SCANNER: 'fake-scanner'}
    API_URL = 'http://scanner.example.org'
    API_KEY = 'api-key'

    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(requests.Session, 'post')
    def test_run_with_mocks(self, requests_mock, incr_mock):
        rule = ScannerRule.objects.create(name='r', scanner=self.FAKE_SCANNER)
        scanner_data = {'matchedRules': [rule.name]}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=self.API_URL,
            json={
                'api_key': self.API_KEY,
                'download_url': self.upload.get_authenticated_download_url(),
            },
            timeout=123,
        )
        result = ScannerResult.objects.all()[0]
        assert result.upload == self.upload
        assert result.scanner == self.FAKE_SCANNER
        assert result.results == scanner_data
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call(f'devhub.{scanner_name}.has_matches'),
                mock.call(f'devhub.{scanner_name}.rule.{rule.id}.match'),
                mock.call(f'devhub.{scanner_name}.success'),
            ]
        )
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_handles_scanner_errors_with_mocks(self, requests_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_throws_errors_with_mocks(self, requests_mock):
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        with self.assertRaises(ValueError):
            run_scanner(
                self.results,
                self.upload.pk,
                scanner=self.FAKE_SCANNER,
                api_url=self.API_URL,
                api_key=self.API_KEY,
            )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        # This call should not raise even though there will be an error because
        # `api_url` is `None`.
        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=None,
            api_key='does-not-matter',
        )

        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        incr_mock.assert_called_with(f'devhub.{scanner_name}.failure')
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch.object(requests.Session, 'post')
    def test_calls_statsd_timer(self, requests_mock, timer_mock):
        requests_mock.return_value = self.create_response()

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert timer_mock.called
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        timer_mock.assert_called_with(f'devhub.{scanner_name}')
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_handles_http_errors_with_mock(self, requests_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        requests_mock.return_value = self.create_response(
            status_code=504, data={'message': 'http timeout'}
        )
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results


class TestRunCustoms(TestCase):
    API_URL = 'http://customs.example.org'
    API_KEY = 'some-api-key'

    def setUp(self):
        super().setUp()

        self.upload_pk = 1234
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS}

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        run_scanner_mock.return_value = self.results

        returned_results = run_customs(self.results, self.upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(
            self.results,
            self.upload_pk,
            scanner=CUSTOMS,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )
        assert returned_results == self.results

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_does_not_run_when_results_contain_errors(self, run_scanner_mock):
        self.results.update({'errors': 1})

        returned_results = run_customs(self.results, self.upload_pk)

        assert not run_scanner_mock.called
        assert returned_results == self.results


class TestRunYara(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all files in the xpi.
        rule = ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 2
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'index.js'},
        }
        assert yara_result.results[1] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_with_invalid_filename(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all files in the xpi.
        rule = ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )
        self.upload = self.get_upload('archive-with-invalid-chars-in-filenames.zip')

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        print(yara_result.results[0])
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'path\\to\\file.txt'},
        }
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_json(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for just all *.json files
        rule = ScannerRule.objects.create(
            name='json_true',
            scanner=YARA,
            # 'is_json_file' is an external variable we automatically provide.
            definition='rule json_true { condition: is_json_file and true }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_manifest(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for just the manifest.json
        rule = ScannerRule.objects.create(
            name='is_manifest_true',
            scanner=YARA,
            # 'is_manifest_file' is an external variable we automatically
            # provide.
            definition='rule is_manifest_true { condition: is_manifest_file }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_locale_file(self, incr_mock):
        self.upload = self.get_upload('notify-link-clicks-i18n.xpi')
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all _locales/*/messages.json files
        rule = ScannerRule.objects.create(
            name='is_locale_true',
            scanner=YARA,
            # 'is_locale_file' is an external variable we automatically
            # provide.
            definition='rule is_locale_true { condition: is_locale_file }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 7
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/de/messages.json'},
        }
        assert yara_result.results[1] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/en/messages.json'},
        }
        assert yara_result.results[2] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/ja/messages.json'},
        }
        assert yara_result.results[3] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/nb_NO/messages.json'},
        }
        assert yara_result.results[4] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/nl/messages.json'},
        }
        assert yara_result.results[5] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/ru/messages.json'},
        }
        assert yara_result.results[6] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/sv/messages.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_matches(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This compiled rule will never match.
        ScannerRule.objects.create(
            name='always_false',
            scanner=YARA,
            definition='rule always_false { condition: false }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.results == []
        # The task should always return the results.
        assert received_results == self.results
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_called_with('devhub.yara.success')

    def test_run_ignores_directories(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }
        # This rule will match for all files in the xpi.
        ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )

        received_results = run_yara(results, upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(yara_result.results) == 3
        # The task should always return the results.
        assert received_results == results

    def test_run_skips_disabled_yara_rules(self):
        assert len(ScannerResult.objects.all()) == 0
        # This rule should match for all files in the xpi but it is disabled.
        ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
            is_active=False,
        )

        run_yara(self.results, self.upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 0

    @mock.patch('yara.compile')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock, yara_compile_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        yara_compile_mock.side_effect = Exception()

        # We use `_run_yara()` because `run_yara()` is decorated with
        # `@validation_task`, which gracefully handles exceptions.
        received_results = _run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('yara.compile')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_throws_errors(self, incr_mock, yara_compile_mock):
        yara_compile_mock.side_effect = Exception()

        # We use `_run_yara()` because `run_yara()` is decorated with
        # `@validation_task`, which gracefully handles exceptions.
        with self.assertRaises(Exception):
            _run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')

    @mock.patch('olympia.scanners.tasks.statsd.timer')
    def test_calls_statsd_timer(self, timer_mock):
        run_yara(self.results, self.upload.pk)

        assert timer_mock.called
        timer_mock.assert_called_with('devhub.yara')

    @mock.patch('yara.compile')
    def test_does_not_run_when_results_contain_errors(self, yara_compile_mock):
        self.results.update({'errors': 1})
        received_results = run_yara(self.results, self.upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == self.results

    def test_run_in_binary_mode(self):
        self.upload = self.get_upload('webextension_with_image.zip')

        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all PNG files in the xpi.
        rule = ScannerRule.objects.create(
            name='match_png',
            scanner=YARA,
            definition='rule match_png { '
            'strings: $png = { 89 50 4E 47 0D 0A 1A 0A } '
            'condition: $png at 0 }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'img.png'},
        }
        # The task should always return the results.
        assert received_results == self.results


class TestRunYaraQueryRule(TestCase):
    def setUp(self):
        super().setUp()

        self.version = addon_factory(
            file_kw={'filename': 'webextension.xpi'}
        ).current_version

        # This rule will match for all files in the xpi.
        self.rule = ScannerQueryRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
            state=NEW,
        )

        # Just to be sure we're always starting fresh.
        assert len(ScannerQueryResult.objects.all()) == 0

    def test_run(self):
        # Pretend we went through the admin.
        self.rule.update(state=SCHEDULED)

        # Similar to test_run_on_chunk() except it needs to find the versions
        # by itself.
        other_addon = addon_factory(
            version_kw={'created': self.days_ago(1)},
            file_kw={'filename': 'webextension.xpi'},
        )
        other_addon_previous_current_version = other_addon.current_version
        included_versions = [
            # Only listed webextension version on this add-on.
            self.version,
            # Unlisted webextension version of this add-on.
            addon_factory(
                disabled_by_user=True,  # Doesn't matter.
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'filename': 'webextension.xpi'},
            ).versions.get(),
            # Unlisted webextension version of an add-on that has multiple
            # versions.
            version_factory(
                addon=other_addon,
                created=self.days_ago(42),
                channel=amo.CHANNEL_UNLISTED,
                file_kw={'filename': 'webextension.xpi'},
            ),
            # Listed webextension versions of an add-on that has multiple
            # versions.
            other_addon_previous_current_version,
            version_factory(
                addon=other_addon, file_kw={'filename': 'webextension.xpi'}
            ),
        ]
        # Ignored versions:
        # Listed Webextension version belonging to mozilla disabled add-on.
        addon_factory(
            status=amo.STATUS_DISABLED, file_kw={'filename': 'webextension.xpi'}
        ).current_version
        # Unlisted extension without a File instance
        Version.objects.create(
            addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='42.42.42.42'
        )
        # Unlisted extension with a File... but no File.file
        File.objects.create(
            manifest_version=2,
            version=Version.objects.create(
                addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='43.43.43.43'
            ),
        )

        # Run the task.
        run_yara_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == len(included_versions)
        assert sorted(
            ScannerQueryResult.objects.values_list('version_id', flat=True)
        ) == sorted(v.pk for v in included_versions)
        self.rule.reload()
        assert self.rule.state == COMPLETED
        assert self.rule.task_count == 1
        # We run tests in eager mode, so we can't retrieve the result for real,
        # just make sure the id was set to something.
        assert self.rule.celery_group_result_id is not None

    def test_run_on_disabled_addons(self):
        self.version.addon.update(status=amo.STATUS_DISABLED)
        self.rule.update(run_on_disabled_addons=True, state=SCHEDULED)
        run_yara_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == 1
        assert ScannerQueryResult.objects.get().version == self.version
        self.rule.reload()
        assert self.rule.state == COMPLETED

    def test_run_not_new(self):
        self.rule.update(state=RUNNING)  # Not SCHEDULED.
        run_yara_query_rule.delay(self.rule.pk)

        # Nothing should have changed.
        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == RUNNING

    def test_mark_yara_query_rule_as_completed(self):
        self.rule.update(state=RUNNING)
        mark_yara_query_rule_as_completed_or_aborted(self.rule.pk)
        self.rule.reload()
        assert self.rule.state == COMPLETED

    def test_mark_yara_query_rule_as_aborted(self):
        self.rule.update(state=ABORTING)
        mark_yara_query_rule_as_completed_or_aborted(self.rule.pk)
        self.rule.reload()
        assert self.rule.state == ABORTED

    def test_run_on_chunk_aborting(self):
        self.rule.update(state=ABORTING)
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        assert ScannerQueryResult.objects.count() == 0

        self.rule.reload()
        assert self.rule.state == ABORTING  # Not touched by this.

    def test_run_on_chunk_aborted(self):
        # This shouldn't happen - if there are any tasks left, state should be
        # RUNNING or ABORTING, but let's make sure we handle it.
        self.rule.update(state=ABORTED)
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == ABORTED  # Not touched by this.

    def test_run_on_chunk(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        yara_results = ScannerQueryResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.version == self.version
        assert not yara_result.was_blocked
        assert len(yara_result.results) == 2
        assert yara_result.results[0] == {
            'rule': self.rule.name,
            'tags': [],
            'meta': {'filename': 'index.js'},
        }
        assert yara_result.results[1] == {
            'rule': self.rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        self.rule.reload()
        assert self.rule.state == RUNNING  # Not touched by this task.

    def test_run_on_chunk_was_blocked(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        block_factory(addon=self.version.addon, updated_by=user_factory())
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        yara_results = ScannerQueryResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.version == self.version
        assert yara_result.was_blocked

    def test_run_on_chunk_not_blocked(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        self.version.update(version='2.0')
        another_version = version_factory(
            addon=self.version.addon, channel=amo.CHANNEL_UNLISTED
        )
        block_factory(
            addon=self.version.addon,
            updated_by=user_factory(),
            version_ids=[another_version.id],
        )
        block_factory(
            addon=addon_factory(guid='@differentguid'),
            updated_by=user_factory(),
        )
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        yara_results = ScannerQueryResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.version == self.version
        assert not yara_result.was_blocked

    def test_run_on_chunk_disabled(self):
        # Make sure it still works when a file has been disabled
        File.objects.filter(pk=self.version.file.pk).update(status=amo.STATUS_DISABLED)
        self.test_run_on_chunk()

    def test_dont_generate_results_if_not_matching_rule(self):
        # Unlike "regular" ScannerRule/ScannerResult, for query stuff we don't
        # store a result instance if the version doesn't match the rule.
        self.rule.update(definition='rule always_false { condition: false }')
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)
        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == NEW  # Not touched by this task.


class TestCallMadApi(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = [
            {
                **amo.VALIDATOR_SKELETON_RESULTS,
            }
        ]
        self.customs_result = ScannerResult.objects.create(
            upload=self.upload,
            scanner=CUSTOMS,
            results={'scanMap': {'a': 1, 'b': 2}},
        )
        self.yara_result = ScannerResult.objects.create(
            upload=self.upload, scanner=YARA, results=[{'rule': 'fake'}]
        )
        self.default_results_count = len(ScannerResult.objects.all())
        self.create_switch('enable-mad', active=True)

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @mock.patch('olympia.scanners.tasks.uuid.uuid4')
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(requests.Session, 'post')
    def test_call_with_mocks(self, requests_mock, incr_mock, timer_mock, uuid4_mock):
        model_version = 'x.y.z'
        ml_results = {
            'ensemble': 0.56,
            'scanners': {
                'customs': {'score': 0.123, 'model_version': model_version},
            },
        }
        requests_mock.return_value = self.create_response(data=ml_results)
        requestId = 'some request id'
        uuid4_mock.return_value.hex = requestId
        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert self.customs_result.score == -1.0
        assert self.customs_result.model_version is None

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=settings.MAD_API_URL,
            json={'scanners': {'customs': self.customs_result.results}},
            timeout=settings.MAD_API_TIMEOUT,
            headers={'x-request-id': requestId},
        )
        assert len(ScannerResult.objects.all()) == self.default_results_count + 1
        mad_result = ScannerResult.objects.latest()
        assert mad_result.upload == self.upload
        assert mad_result.scanner == MAD
        assert mad_result.results == ml_results
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.mad.success')])
        assert timer_mock.called
        timer_mock.assert_called_with('devhub.mad')
        # The customs and mad results should be updated with the scores
        # returned in the ML response.
        self.customs_result.refresh_from_db()
        assert self.customs_result.score == Decimal('0.123')
        assert self.customs_result.model_version == model_version
        assert mad_result.score == Decimal('0.56')
        assert mad_result.model_version is None

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(requests.Session, 'post')
    def test_handles_non_200_http_responses(self, requests_mock, incr_mock):
        requests_mock.return_value = self.create_response(
            status_code=504, data={'message': 'http timeout'}
        )

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.mad.failure')])

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(requests.Session, 'post')
    def test_handles_non_json_responses(self, requests_mock, incr_mock):
        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError('not json')
        requests_mock.return_value = response

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.mad.failure')])

    @mock.patch.object(requests.Session, 'post')
    def test_does_not_run_when_switch_is_off(self, requests_mock):
        self.create_switch('enable-mad', active=False)

        call_mad_api(self.results, self.upload.pk)

        assert not requests_mock.called

    @mock.patch.object(requests.Session, 'post')
    def test_does_not_run_when_results_contain_errors(self, requests_mock):
        self.create_switch('enable-mad', active=True)
        self.results[0].update({'errors': 1})

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert not requests_mock.called
        assert returned_results == self.results[0]

    @mock.patch.object(requests.Session, 'post')
    def test_does_not_run_when_scan_map_is_empty(self, requests_mock):
        self.create_switch('enable-mad', active=True)
        self.customs_result.update(results={'scanMap': {}})

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert not requests_mock.called
        assert returned_results == self.results[0]

    @mock.patch.object(requests.Session, 'post')
    def test_does_not_run_when_scan_map_is_small(self, requests_mock):
        self.create_switch('enable-mad', active=True)
        self.customs_result.update(results={'scanMap': {'a': 1}})

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert not requests_mock.called
        assert returned_results == self.results[0]

    @mock.patch.object(requests.Session, 'post')
    def test_does_not_run_when_other_results_have_errors(self, requests_mock):
        self.create_switch('enable-mad', active=True)
        self.results.append({**amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT})
        assert len(self.results) == 2

        returned_results = call_mad_api(self.results, self.upload.pk)

        assert not requests_mock.called
        assert returned_results == self.results[1]
