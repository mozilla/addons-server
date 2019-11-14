from datetime import datetime, timedelta
from unittest import mock

import pytest
import yara

from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants.scanners import (
    CUSTOMS,
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    FLAG_FOR_HUMAN_REVIEW,
    NO_ACTION,
    WAT,
    YARA,
)
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.scanners.tasks import (
    run_scanner,
    run_customs,
    run_wat,
    run_yara,
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _flag_for_human_review,
    _no_action,
    run_action,
)


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
        scanner_data = {'some': 'results'}
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
        incr_mock.assert_called_with('devhub.{}.success'.format(scanner_name))
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
    def test_run_with_mocks(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0

        rule = ScannerRule.objects.create(name='always_true', scanner=YARA)
        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule %s { condition: true }' % rule.name)
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(self.results, self.upload.pk)

        assert yara_compile_mock.called
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
        assert incr_mock.call_count == 2
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_matches_with_mocks(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0

        # This compiled rule will never match.
        rules = yara.compile(source='rule always_false { condition: false }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
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
        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')

        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(results, upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(yara_result.results) == 3
        # The task should always return the results.
        assert received_results == results

    @override_settings(YARA_RULES_FILEPATH='unknown/path/to/rules.yar')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        # This call should not raise even though there will be an error because
        # YARA_RULES_FILEPATH is configured with a wrong path.
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


class TestActions(TestCase):
    def test_action_does_nothing(self):
        version = version_factory(addon=addon_factory())
        _no_action(version)

    def test_flags_a_version_for_human_review(self):
        version = version_factory(addon=addon_factory())
        assert not version.needs_human_review
        _flag_for_human_review(version)
        assert version.needs_human_review
        version.reload()
        assert version.needs_human_review

    def test_delay_auto_approval(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.needs_human_review
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24))
        assert version.needs_human_review

    def test_delay_auto_approval_indefinitely(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.needs_human_review
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version)
        assert addon.auto_approval_delayed_until == datetime.max
        assert version.needs_human_review


class TestRunAction(TestCase):
    def setUp(self):
        super(TestRunAction, self).setUp()

        self.scanner = YARA
        self.version = version_factory(addon=addon_factory())
        self.scanner_rule = ScannerRule.objects.create(
            name='rule-1', scanner=self.scanner, action=NO_ACTION
        )
        self.scanner_result = ScannerResult.objects.create(
            version=self.version, scanner=self.scanner
        )
        self.scanner_result.matched_rules.add(self.scanner_rule)

    @mock.patch('olympia.scanners.tasks._no_action')
    def test_runs_no_action(self, no_action_mock):
        self.scanner_rule.update(action=NO_ACTION)

        run_action(self.version.id)

        assert no_action_mock.called
        no_action_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.tasks._flag_for_human_review')
    def test_runs_flag_for_human_review(self, flag_for_human_review_mock):
        self.scanner_rule.update(action=FLAG_FOR_HUMAN_REVIEW)

        run_action(self.version.id)

        assert flag_for_human_review_mock.called
        flag_for_human_review_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.tasks._delay_auto_approval')
    def test_runs_delay_auto_approval(self, _delay_auto_approval_mock):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL)

        run_action(self.version.id)

        assert _delay_auto_approval_mock.called
        _delay_auto_approval_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.tasks._delay_auto_approval_indefinitely')
    def test_runs_delay_auto_approval_indefinitely(
            self, _delay_auto_approval_indefinitely_mock):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL_INDEFINITELY)

        run_action(self.version.id)

        assert _delay_auto_approval_indefinitely_mock.called
        _delay_auto_approval_indefinitely_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.tasks.log.info')
    def test_returns_when_no_action_found(self, log_mock):
        self.scanner_rule.delete()

        run_action(self.version.id)

        log_mock.assert_called_with(
            'No action to execute for version %s.', self.version.id
        )

    def test_raise_when_action_is_invalid(self):
        # `12345` is an invalid action ID
        self.scanner_rule.update(action=12345)

        with pytest.raises(Exception, match='invalid action 12345'):
            run_action(self.version.id)

    @mock.patch('olympia.scanners.tasks._no_action')
    @mock.patch('olympia.scanners.tasks._flag_for_human_review')
    def test_selects_the_action_with_the_highest_severity(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`.
        rule = ScannerRule.objects.create(
            name='rule-2', scanner=self.scanner, action=FLAG_FOR_HUMAN_REVIEW
        )
        self.scanner_result.matched_rules.add(rule)

        run_action(self.version.id)

        assert not no_action_mock.called
        assert flag_for_human_review_mock.called

    @mock.patch('olympia.scanners.tasks._no_action')
    @mock.patch('olympia.scanners.tasks._flag_for_human_review')
    def test_selects_active_actions_only(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`. In this test
        # case, we disable this rule, though.
        rule = ScannerRule.objects.create(
            name='rule-2',
            scanner=self.scanner,
            action=FLAG_FOR_HUMAN_REVIEW,
            is_active=False,
        )
        self.scanner_result.matched_rules.add(rule)

        run_action(self.version.id)

        assert no_action_mock.called
        assert not flag_for_human_review_mock.called
