import yara

from unittest import mock

from django.test.utils import override_settings

from olympia.amo.tests import TestCase
from olympia.files.tests.test_models import UploadTest
from olympia.yara.models import YaraResult
from olympia.yara.tasks import run_yara


class TestRunYara(UploadTest, TestCase):
    @mock.patch('yara.compile')
    def test_skip_non_xpi_files_with_mocks(self, yara_compile_mock):
        upload = self.get_upload('search.xml')

        run_yara(upload.pk)

        assert not yara_compile_mock.called

    @mock.patch('olympia.yara.tasks.statsd.incr')
    def test_run_with_mocks(self, incr_mock):
        upload = self.get_upload('webextension.xpi')
        assert len(YaraResult.objects.all()) == 0

        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            run_yara(upload.pk)

        assert yara_compile_mock.called
        results = YaraResult.objects.all()
        assert len(results) == 1
        result = results[0]
        assert result.upload == upload
        assert len(result.matches) == 2
        assert result.matches[0] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {
                'filename': 'index.js'
            },
        }
        assert result.matches[1] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {
                'filename': 'manifest.json'
            },
        }
        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.success')

    def test_run_no_matches_with_mocks(self):
        upload = self.get_upload('webextension.xpi')
        assert len(YaraResult.objects.all()) == 0

        # This compiled rule will never match.
        rules = yara.compile(source='rule always_false { condition: false }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            run_yara(upload.pk)

        result = YaraResult.objects.all()[0]
        assert result.matches == []

    def test_run_ignores_directories(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')

        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            run_yara(upload.pk)

        result = YaraResult.objects.all()[0]
        assert result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(result.matches) == 3

    @override_settings(YARA_RULES_FILEPATH='unknown/path/to/rules.yar')
    @mock.patch('olympia.yara.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        upload = self.get_upload('webextension.xpi')

        # This call should not raise even though there will be an error because
        # YARA_RULES_FILEPATH is configured with a wrong path.
        run_yara(upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')

    @mock.patch('olympia.yara.tasks.statsd.timer')
    def test_calls_statsd_timer(self, timer_mock):
        upload = self.get_upload('webextension.xpi')

        run_yara(upload.pk)

        assert timer_mock.called
        timer_mock.assert_called_with('devhub.yara')
