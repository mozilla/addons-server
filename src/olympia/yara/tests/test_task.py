import yara

from unittest import mock

from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.files.tests.test_models import UploadTest
from olympia.yara.models import YaraResult
from olympia.yara.tasks import run_yara


class TestRunYara(UploadTest, TestCase):
    def setUp(self):
        super(TestRunYara, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS, 'metadata': {
            'is_webextension': True,
        }}

    @mock.patch('yara.compile')
    def test_skip_non_webextensions_with_mocks(self, yara_compile_mock):
        upload = self.get_upload('search.xml')
        results = {**amo.VALIDATOR_SKELETON_RESULTS, 'metadata': {
            'is_webextension': False,
        }}

        received_results = run_yara(results, upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == results

    @mock.patch('olympia.yara.tasks.statsd.incr')
    def test_run_with_mocks(self, incr_mock):
        assert len(YaraResult.objects.all()) == 0

        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(self.results, self.upload.pk)

        assert yara_compile_mock.called
        yara_results = YaraResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.matches) == 2
        assert yara_result.matches[0] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {
                'filename': 'index.js'
            },
        }
        assert yara_result.matches[1] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {
                'filename': 'manifest.json'
            },
        }
        assert incr_mock.called
        assert incr_mock.call_count == 2
        incr_mock.assert_has_calls([
            mock.call('devhub.yara.has_matches'),
            mock.call('devhub.yara.success'),
        ])
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.yara.tasks.statsd.incr')
    def test_run_no_matches_with_mocks(self, incr_mock):
        assert len(YaraResult.objects.all()) == 0

        # This compiled rule will never match.
        rules = yara.compile(source='rule always_false { condition: false }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(self.results, self.upload.pk)

        yara_result = YaraResult.objects.all()[0]
        assert yara_result.matches == []
        # The task should always return the results.
        assert received_results == self.results
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_called_with('devhub.yara.success')

    def test_run_ignores_directories(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        results = {**amo.VALIDATOR_SKELETON_RESULTS, 'metadata': {
            'is_webextension': True,
        }}
        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')

        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(results, upload.pk)

        yara_result = YaraResult.objects.all()[0]
        assert yara_result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(yara_result.matches) == 3
        # The task should always return the results.
        assert received_results == results

    @override_settings(YARA_RULES_FILEPATH='unknown/path/to/rules.yar')
    @mock.patch('olympia.yara.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        # This call should not raise even though there will be an error because
        # YARA_RULES_FILEPATH is configured with a wrong path.
        received_results = run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.yara.tasks.statsd.timer')
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
