import os
import shutil
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import (
    addon_factory,
    AMOPaths,
    TestCase,
    version_factory,
)
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    ML_API,
    NEW,
    RUNNING,
    SCHEDULED,
    WAT,
    YARA,
)
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.models import (
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
)
from olympia.scanners.tasks import (
    call_ml_api,
    mark_yara_query_rule_as_completed_or_aborted,
    run_scanner,
    run_customs,
    run_wat,
    run_yara,
    run_yara_query_rule,
    run_yara_query_rule_on_versions_chunk,
)
from olympia.versions.models import Version


class TestRunScanner(UploadTest, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = {FAKE_SCANNER: 'fake-scanner'}
    API_URL = 'http://scanner.example.org'
    API_KEY = 'api-key'

    def setUp(self):
        super(TestRunScanner, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': True},
        }

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_skip_non_webextensions(self):
        upload = self.get_upload('search.xml')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': False},
        }

        returned_results = run_scanner(
            results,
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == results

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch('olympia.scanners.tasks.requests.post')
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
                mock.call('devhub.{}.has_matches'.format(scanner_name)),
                mock.call(
                    'devhub.{}.rule.{}.match'.format(scanner_name, rule.id)
                ),
                mock.call('devhub.{}.success'.format(scanner_name)),
            ]
        )
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_scanner_errors_with_mocks(self, requests_mock):
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
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
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
        incr_mock.assert_called_with('devhub.{}.failure'.format(scanner_name))
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch('olympia.scanners.tasks.requests.post')
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
        timer_mock.assert_called_with('devhub.{}'.format(scanner_name))
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_http_errors_with_mock(self, requests_mock):
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
        super(TestRunCustoms, self).setUp()

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


class TestRunWat(TestCase):
    API_URL = 'http://wat.example.org'
    API_KEY = 'some-api-key'

    def setUp(self):
        super(TestRunWat, self).setUp()

        self.upload_pk = 1234
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS}

    @override_settings(WAT_API_URL=API_URL, WAT_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        run_scanner_mock.return_value = self.results

        returned_results = run_wat(self.results, self.upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(
            self.results,
            self.upload_pk,
            scanner=WAT,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )
        assert returned_results == self.results

    @override_settings(WAT_API_URL=API_URL, WAT_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_does_not_run_when_results_contain_errors(self, run_scanner_mock):
        self.results.update({'errors': 1})

        returned_results = run_wat(self.results, self.upload_pk)

        assert not run_scanner_mock.called
        assert returned_results == self.results


class TestRunYara(UploadTest, TestCase):
    def setUp(self):
        super(TestRunYara, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': True},
        }

    @mock.patch('yara.compile')
    def test_skip_non_webextensions_with_mocks(self, yara_compile_mock):
        upload = self.get_upload('search.xml')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': False},
        }

        received_results = run_yara(results, upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == results

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
            'metadata': {'is_webextension': True},
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
        yara_compile_mock.side_effect = Exception()

        received_results = run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')
        # The task should always return the results.
        assert received_results == self.results

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


class TestRunYaraQueryRule(AMOPaths, TestCase):
    def setUp(self):
        super().setUp()

        self.version = addon_factory(
            file_kw={'is_webextension': True}
        ).current_version
        self.xpi_copy_over(self.version.all_files[0], 'webextension.xpi')

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
            file_kw={'is_webextension': True},
            version_kw={'created': self.days_ago(1)},
        )
        other_addon_previous_current_version = other_addon.current_version
        included_versions = [
            # Only listed webextension version on this add-on.
            self.version,
            # Unlisted webextension version of this add-on.
            addon_factory(
                disabled_by_user=True,  # Doesn't matter.
                file_kw={'is_webextension': True},
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
            ).versions.get(),
            # Unlisted webextension version of an add-on that has multiple
            # versions.
            version_factory(
                addon=other_addon,
                created=self.days_ago(42),
                channel=amo.RELEASE_CHANNEL_UNLISTED,
                file_kw={'is_webextension': True},
            ),
            # Listed webextension versions of an add-on that has multiple
            # versions.
            other_addon_previous_current_version,
            version_factory(
                addon=other_addon, file_kw={'is_webextension': True}
            ),
        ]
        # Ignored versions:
        # Listed Webextension version belonging to mozilla disabled add-on.
        addon_factory(
            file_kw={'is_webextension': True}, status=amo.STATUS_DISABLED
        ).current_version
        # Non-Webextension
        addon_factory(file_kw={'is_webextension': False}).current_version

        for version in Version.objects.all():
            self.xpi_copy_over(version.all_files[0], 'webextension.xpi')

        # Run the task.
        run_yara_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == len(included_versions)
        assert sorted(
            ScannerQueryResult.objects.values_list('version_id', flat=True)
        ) == sorted(v.pk for v in included_versions)
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

    def test_run_on_chunk_fallback_path(self):
        # Make sure it still works when a file has been disabled but the path
        # has not been moved to the guarded location yet (we fall back to the
        # other path).
        # We avoid triggering the on_change callback that would move the file
        # when the status is updated by doing an update() on the queryset.
        File.objects.filter(pk=self.version.all_files[0].pk).update(
            status=amo.STATUS_DISABLED)
        self.test_run_on_chunk()

    def test_run_on_chunk_fallback_path_guarded(self):
        # Like test_run_on_chunk_fallback_path() but starting with a public
        # File instance that somehow still has its file in the guarded path
        # (Would happen if the whole add-on was disabled then re-enabled and
        # the files haven't been moved back to the public location yet).
        file_ = self.version.all_files[0]
        if not os.path.exists(os.path.dirname(file_.guarded_file_path)):
            os.makedirs(os.path.dirname(file_.guarded_file_path))
        shutil.move(file_.file_path, file_.guarded_file_path)
        self.test_run_on_chunk()

    def test_dont_generate_results_if_not_matching_rule(self):
        # Unlike "regular" ScannerRule/ScannerResult, for query stuff we don't
        # store a result instance if the version doesn't match the rule.
        self.rule.update(definition='rule always_false { condition: false }')
        run_yara_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)
        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == NEW  # Not touched by this task.


class TestCallMlApi(UploadTest, TestCase):
    ML_API_URL = 'http://ml.example.org'

    def setUp(self):
        super(TestCallMlApi, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = [
            {
                **amo.VALIDATOR_SKELETON_RESULTS,
                'metadata': {'is_webextension': True},
            }
        ]
        self.customs_result = ScannerResult.objects.create(
            upload=self.upload,
            scanner=CUSTOMS,
            results={'some': 'customs results'},
        )
        self.yara_result = ScannerResult.objects.create(
            upload=self.upload, scanner=YARA, results=[{'rule': 'fake'}]
        )
        self.default_results_count = len(ScannerResult.objects.all())
        self.create_switch('enable-scanner-ml-api-call', active=True)

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    def test_skip_non_webextensions(self):
        upload = self.get_upload('search.xml')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': False},
        }

        returned_results = call_ml_api([results], upload.pk)

        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert returned_results == results

    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_call_with_mocks(self, requests_mock, incr_mock, timer_mock):
        ml_results = {'some': 'results'}
        requests_mock.return_value = self.create_response(data=ml_results)
        assert len(ScannerResult.objects.all()) == self.default_results_count

        returned_results = call_ml_api(self.results, self.upload.pk)

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=settings.ML_API_URL,
            json={'customs': self.customs_result.results},
            timeout=settings.ML_API_TIMEOUT,
        )
        assert (
            len(ScannerResult.objects.all()) == self.default_results_count + 1
        )
        last_result = ScannerResult.objects.latest()
        assert last_result.upload == self.upload
        assert last_result.scanner == ML_API
        assert last_result.results == ml_results
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.ml_api.success')])
        assert timer_mock.called
        timer_mock.assert_called_with('devhub.ml_api')

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_non_200_http_responses(self, requests_mock, incr_mock):
        requests_mock.return_value = self.create_response(
            status_code=504, data={'message': 'http timeout'}
        )

        returned_results = call_ml_api(self.results, self.upload.pk)

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.ml_api.failure')])

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_non_json_responses(self, requests_mock, incr_mock):
        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError('not json')
        requests_mock.return_value = response

        returned_results = call_ml_api(self.results, self.upload.pk)

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == self.default_results_count
        assert returned_results == self.results[0]
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls([mock.call('devhub.ml_api.failure')])

    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_does_not_run_when_switch_is_off(self, requests_mock):
        self.create_switch('enable-scanner-ml-api-call', active=False)

        call_ml_api(self.results, self.upload.pk)

        assert not requests_mock.called
