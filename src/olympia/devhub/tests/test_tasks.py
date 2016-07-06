import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.test.utils import override_settings

import mock
import pytest
from PIL import Image

from olympia import amo
from olympia.applications.models import AppVersion
from olympia.amo.tests import TestCase
from olympia.constants.base import VALIDATOR_SKELETON_RESULTS
from olympia.addons.models import Addon
from olympia.amo.helpers import user_media_path
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.devhub import tasks
from olympia.files.models import FileUpload
from olympia.versions.models import Version


ADDON_TEST_FILES = os.path.join(os.path.dirname(__file__), 'addons')
pytestmark = pytest.mark.django_db


def get_addon_file(name):
    return os.path.join(ADDON_TEST_FILES, name)


def test_resize_icon_shrink():
    """ Image should be shrunk so that the longest side is 32px. """

    resize_size = 32
    final_size = (32, 12)

    _uploader(resize_size, final_size)


def test_resize_icon_enlarge():
    """ Image stays the same, since the new size is bigger than both sides. """

    resize_size = 350
    final_size = (339, 128)

    _uploader(resize_size, final_size)


def test_resize_icon_same():
    """ Image stays the same, since the new size is the same. """

    resize_size = 339
    final_size = (339, 128)

    _uploader(resize_size, final_size)


def test_resize_icon_list():
    """ Resize multiple images at once. """

    resize_size = [32, 339, 350]
    final_size = [(32, 12), (339, 128), (339, 128)]

    _uploader(resize_size, final_size)


def _uploader(resize_size, final_size):
    img = get_image_path('mozilla.png')
    original_size = (339, 128)

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)

    # resize_icon removes the original
    shutil.copyfile(img, src.name)

    src_image = Image.open(src.name)
    assert src_image.size == original_size

    if isinstance(final_size, list):
        uploadto = user_media_path('addon_icons')
        try:
            os.makedirs(uploadto)
        except OSError:
            pass
        for rsize, fsize in zip(resize_size, final_size):
            dest_name = os.path.join(uploadto, '1234')

            tasks.resize_icon(src.name, dest_name, resize_size, locally=True)
            dest_image = Image.open(open('%s-%s.png' % (dest_name, rsize)))
            assert dest_image.size == fsize

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
        shutil.rmtree(uploadto)
    else:
        dest = tempfile.mktemp(suffix='.png')
        tasks.resize_icon(src.name, dest, resize_size, locally=True)
        dest_image = Image.open(dest)
        assert dest_image.size == final_size

    assert not os.path.exists(src.name)


class ValidatorTestCase(TestCase):
    def setUp(self):
        # 3.7a1pre is somehow required to exist by
        # amo-validator.
        # The other ones are app-versions we're using in our
        # tests
        self.create_appversion('firefox', '3.7a1pre')
        self.create_appversion('firefox', '38.0a1')

        # Required for WebExtensions
        self.create_appversion('firefox', '*')
        self.create_appversion('firefox', '42.0')
        self.create_appversion('firefox', '43.0')

    def create_appversion(self, name, version):
        return AppVersion.objects.create(
            application=amo.APPS[name].id, version=version)


class TestValidator(ValidatorTestCase):
    mock_sign_addon_warning = json.dumps({
        "warnings": 1,
        "errors": 0,
        "messages": [
            {"context": None,
             "editors_only": False,
             "description": "Add-ons which are already signed will be "
                            "re-signed when published on AMO. This will "
                            "replace any existing signatures on the add-on.",
             "column": None,
             "type": "warning",
             "id": ["testcases_content", "signed_xpi"],
             "file": "",
             "tier": 2,
             "for_appversions": None,
             "message": "Package already signed",
             "uid": "87326f8f699f447e90b3d5a66a78513e",
             "line": None,
             "compatibility_type": None},
        ]
    })

    def setUp(self):
        super(TestValidator, self).setUp()
        self.upload = FileUpload.objects.create(
            path=get_addon_file('desktop.xpi'))
        assert not self.upload.valid

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        assert self.get_upload().valid

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        tasks.validate(self.upload)
        assert not self.get_upload().valid

    @mock.patch('validator.submain.test_package')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception

        self.upload.update(path=get_addon_file('desktop.xpi'))

        assert self.upload.validation is None

        tasks.validate(self.upload)
        self.upload.reload()
        validation = self.upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == ['validator',
                                                   'unexpected_exception']
        assert not self.upload.valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validation_error_webextension(self, _mock):
        _mock.side_effect = Exception
        self.upload.update(path=get_addon_file('valid_webextension.xpi'))

        assert self.upload.validation is None

        tasks.validate(self.upload)
        self.upload.reload()
        validation = self.upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == [
            'validator', 'unexpected_exception']
        assert 'WebExtension' in validation['messages'][0]['message']
        assert not self.upload.valid

    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=False)
    @mock.patch('olympia.devhub.tasks.annotate_validation_results')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_annotation_error(self, run_validator, annotate):
        """Test that an error that occurs during annotation is saved as an
        error result."""
        annotate.side_effect = Exception
        run_validator.return_value = '{"errors": 0}'

        assert self.upload.validation is None

        tasks.validate(self.upload)
        self.upload.reload()

        validation = self.upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == ['validator',
                                                   'unexpected_exception']
        assert not self.upload.valid

    @override_settings(SIGNING_SERVER='http://full',
                       PRELIMINARY_SIGNING_SERVER='http://prelim')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_validation_signing_warning(self, _mock):
        """If we sign addons, warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['warnings'] == 1
        assert len(validation['messages']) == 1

    @override_settings(SIGNING_SERVER='', PRELIMINARY_SIGNING_SERVER='')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_validation_no_signing_warning(self, _mock):
        """If we're not signing addon don't warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['warnings'] == 0
        assert len(validation['messages']) == 0

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_annotate_passed_auto_validation(self, _mock):
        """Set passed_auto_validation on reception of the results."""
        result = {'signing_summary': {'trivial': 1, 'low': 0, 'medium': 0,
                                      'high': 0},
                  'errors': 0}

        _mock.return_value = json.dumps(result)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['passed_auto_validation']

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_annotate_failed_auto_validation(self, _mock):
        """Set passed_auto_validation on reception of the results."""
        result = {'signing_summary': {'trivial': 0, 'low': 1, 'medium': 0,
                                      'high': 0},
                  'errors': 0}

        _mock.return_value = json.dumps(result)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert not validation['passed_auto_validation']

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_annotate_passed_auto_validation_bogus_result(self, _mock):
        """Don't set passed_auto_validation, don't fail if results is bogus."""
        _mock.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        assert (json.loads(self.get_upload().validation) ==
                {"passed_auto_validation": True, "errors": 0,
                 "signing_summary": {"high": 0, "medium": 0,
                                     "low": 0, "trivial": 0}})

    @mock.patch('validator.validate.validate')
    @mock.patch('olympia.devhub.tasks.track_validation_stats')
    def test_track_validation_stats(self, mock_track, mock_validate):
        mock_validate.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        mock_track.assert_called_with(mock_validate.return_value)


class TestMeasureValidationTime(TestValidator):

    def setUp(self):
        super(TestMeasureValidationTime, self).setUp()
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

    @contextmanager
    def statsd_timing_mock(self):
        statsd_calls = {}

        def capture_timing_call(metric, value):
            statsd_calls[metric] = value

        with mock.patch('olympia.devhub.tasks.statsd.timing') as mock_timing:
            mock_timing.side_effect = capture_timing_call
            yield statsd_calls

    def approximate_upload_time(self):
        upload_start = utc_millesecs_from_epoch(self.upload.created)
        now = utc_millesecs_from_epoch()
        return now - upload_start

    def assert_milleseconds_are_close(self, actual_ms, calculated_ms,
                                      fuzz=Decimal(300)):
        assert (actual_ms >= (calculated_ms - fuzz) and
                actual_ms <= (calculated_ms + fuzz))

    def handle_upload_validation_result(self):
        validation = amo.VALIDATOR_SKELETON_RESULTS.copy()
        tasks.handle_upload_validation_result(validation, self.upload.pk)

    def test_track_upload_validation_results_time(self):
        with self.statsd_timing_mock() as statsd_calls:
            self.handle_upload_validation_result()

        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls['devhub.validation_results_processed']
        self.assert_milleseconds_are_close(actual_delta, rough_delta)

    def test_track_upload_validation_results_with_file_size(self):
        with self.statsd_timing_mock() as statsd_calls:
            self.handle_upload_validation_result()

        # This test makes sure storage.size() works on a real file.
        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls[
            'devhub.validation_results_processed_per_mb']
        # This value should not be scaled because this package is under 1MB.
        self.assert_milleseconds_are_close(actual_delta, rough_delta)

    def test_scale_large_xpi_times_per_megabyte(self):
        megabyte = Decimal(1024 * 1024)
        file_size_in_mb = Decimal(5)
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = file_size_in_mb * megabyte
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        # Validation times for files larger than 1MB should be scaled.
        rough_delta = self.approximate_upload_time()
        rough_scaled_delta = Decimal(rough_delta) / file_size_in_mb
        actual_scaled_delta = statsd_calls[
            'devhub.validation_results_processed_per_mb']
        self.assert_milleseconds_are_close(actual_scaled_delta,
                                           rough_scaled_delta)

    def test_measure_small_files_in_separate_bucket(self):
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = 500  # less than 1MB
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls[
            'devhub.validation_results_processed_under_1mb']
        self.assert_milleseconds_are_close(actual_delta, rough_delta)

    def test_measure_large_files_in_separate_bucket(self):
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = (2014 * 1024) * 5  # 5MB
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls[
            'devhub.validation_results_processed_over_1mb']
        self.assert_milleseconds_are_close(actual_delta, rough_delta)

    def test_do_not_calculate_scaled_time_for_empty_files(self):
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = 0
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        assert 'devhub.validation_results_processed_per_mb' not in statsd_calls

    def test_ignore_missing_upload_paths_for_now(self):
        with mock.patch('olympia.devhub.tasks.storage.exists') as mock_exists:
            mock_exists.return_value = False
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        assert 'devhub.validation_results_processed' in statsd_calls
        assert 'devhub.validation_results_processed_per_mb' not in statsd_calls
        assert ('devhub.validation_results_processed_under_1mb' not in
                statsd_calls)


class TestTrackValidatorStats(TestCase):

    def setUp(self):
        super(TestTrackValidatorStats, self).setUp()
        patch = mock.patch('olympia.devhub.tasks.statsd.incr')
        self.mock_incr = patch.start()
        self.addCleanup(patch.stop)

    def result(self, **overrides):
        result = VALIDATOR_SKELETON_RESULTS.copy()
        result.update(overrides)
        return json.dumps(result)

    def test_count_all_successes(self):
        tasks.track_validation_stats(self.result(errors=0))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.all.success'
        )

    def test_count_all_errors(self):
        tasks.track_validation_stats(self.result(errors=1))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.all.failure'
        )

    def test_count_listed_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': True}))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.listed.success'
        )

    def test_count_unlisted_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': False}))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.unlisted.success'
        )

    def test_count_unsignable_addon_for_low_error(self):
        tasks.track_validation_stats(self.result(
            errors=1,
            signing_summary={
                'low': 1,
                'medium': 0,
                'high': 0,
            },
            metadata={
                'listed': False,
            },
        ))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.unlisted.is_not_signable'
        )

    def test_count_unsignable_addon_for_medium_error(self):
        tasks.track_validation_stats(self.result(
            errors=1,
            signing_summary={
                'low': 0,
                'medium': 1,
                'high': 0,
            },
            metadata={
                'listed': False,
            },
        ))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.unlisted.is_not_signable'
        )

    def test_count_unsignable_addon_for_high_error(self):
        tasks.track_validation_stats(self.result(
            errors=1,
            signing_summary={
                'low': 0,
                'medium': 0,
                'high': 1,
            },
            metadata={
                'listed': False,
            },
        ))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.unlisted.is_not_signable'
        )

    def test_count_unlisted_signable_addons(self):
        tasks.track_validation_stats(self.result(
            signing_summary={
                'low': 0,
                'medium': 0,
                'high': 0,
            },
            metadata={
                'listed': False,
            },
        ))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.unlisted.is_signable'
        )

    def test_count_listed_signable_addons(self):
        tasks.track_validation_stats(self.result(
            signing_summary={
                'low': 0,
                'medium': 0,
                'high': 0,
            },
            metadata={
                'listed': True,
            },
        ))
        self.mock_incr.assert_any_call(
            'devhub.validator.results.listed.is_signable'
        )


class TestRunAddonsLinter(ValidatorTestCase):

    def setUp(self):
        super(TestRunAddonsLinter, self).setUp()

        valid_path = get_addon_file('valid_webextension.xpi')
        invalid_path = get_addon_file('invalid_webextension_invalid_id.xpi')

        self.valid_upload = FileUpload.objects.create(path=valid_path)
        self.invalid_upload = FileUpload.objects.create(path=invalid_path)

    def get_upload(self, upload):
        return FileUpload.objects.get(pk=upload.pk)

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_calls_run_linter(self, run_linter):
        run_linter.return_value = '{"errors": 0}'

        assert not self.valid_upload.valid

        tasks.validate(self.valid_upload)

        upload = self.get_upload(self.valid_upload)
        assert upload.valid, upload.validation

    def test_run_linter_fail(self):
        tasks.validate(self.invalid_upload)
        assert not self.get_upload(self.invalid_upload).valid

    def test_run_linter_path_doesnt_exist(self):
        with pytest.raises(ValueError) as exc:
            tasks.run_addons_linter('doesntexist')

        assert exc.value.message == (
            'Path "doesntexist" is not a file or directory or '
            'does not exist.')

    def test_run_linter_use_temporary_file_large_output(self):
        TemporaryFile = tempfile.TemporaryFile

        with mock.patch('olympia.devhub.tasks.tempfile.TemporaryFile') as tmpf:
            tmpf.side_effect = lambda *a, **kw: TemporaryFile(*a, **kw)

            # This is a relatively small add-on (1.2M) but generates
            # a hell lot of warnings
            result = json.loads(tasks.run_addons_linter(
                get_addon_file('typo-gecko.xpi')
            ))

            assert tmpf.call_count == 2
            assert result['success']
            assert result['warnings'] > 700
            assert not result['errors']


class TestValidateFilePath(ValidatorTestCase):

    def test_amo_validator_success(self):
        result = tasks.validate_file_path(
            get_addon_file('valid_firefox_addon.xpi'),
            hash_=None, listed=True)
        assert result['success']
        assert not result['errors']
        assert not result['warnings']

    def test_amo_validator_fail_warning(self):
        result = tasks.validate_file_path(
            get_addon_file('invalid_firefox_addon_warning.xpi'),
            hash_=None, listed=True)
        assert not result['success']
        assert not result['errors']
        assert result['warnings']

    def test_amo_validator_fail_error(self):
        result = tasks.validate_file_path(
            get_addon_file('invalid_firefox_addon_error.xpi'),
            hash_=None, listed=True)
        assert not result['success']
        assert result['errors']
        assert not result['warnings']

    def test_amo_validator_addons_linter_success(self):
        result = tasks.validate_file_path(
            get_addon_file('valid_webextension.xpi'),
            hash_=None, listed=True, is_webextension=True)
        assert result['success']
        assert not result['errors']
        assert not result['warnings']

    def test_amo_validator_addons_linter_error(self):
        # This test assumes that `amo-validator` doesn't correctly
        # validate a invalid id in manifest.json
        result = tasks.validate_file_path(
            get_addon_file('invalid_webextension_invalid_id.xpi'),
            hash_=None, listed=True, is_webextension=True)
        assert not result['success']
        assert result['errors']
        assert not result['warnings']


class TestFlagBinary(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestFlagBinary, self).setUp()
        self.addon = Addon.objects.get(pk=3615)

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_flag_binary(self, _mock):
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 1, '
                              '"contains_binary_content": 0}}')
        tasks.flag_binary([self.addon.pk])
        assert Addon.objects.get(pk=self.addon.pk).binary
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 0, '
                              '"contains_binary_content": 1}}')
        tasks.flag_binary([self.addon.pk])
        assert Addon.objects.get(pk=self.addon.pk).binary

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_flag_not_binary(self, _mock):
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 0, '
                              '"contains_binary_content": 0}}')
        tasks.flag_binary([self.addon.pk])
        assert not Addon.objects.get(pk=self.addon.pk).binary

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_flag_error(self, _mock):
        _mock.side_effect = RuntimeError()
        tasks.flag_binary([self.addon.pk])
        assert not Addon.objects.get(pk=self.addon.pk).binary


@mock.patch('olympia.devhub.tasks.send_html_mail_jinja')
def test_send_welcome_email(send_html_mail_jinja_mock):
    tasks.send_welcome_email(3615, ['del@icio.us'], {'omg': 'yes'})
    send_html_mail_jinja_mock.assert_called_with(
        'Mozilla Add-ons: Thanks for submitting a Firefox Add-on!',
        'devhub/email/submission.html',
        'devhub/email/submission.txt',
        {'omg': 'yes'},
        recipient_list=['del@icio.us'],
        from_email=settings.NOBODY_EMAIL,
        use_blacklist=False,
        perm_setting='individual_contact',
        headers={'Reply-To': settings.EDITORS_EMAIL})


class TestSubmitFile(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestSubmitFile, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        patcher = mock.patch('olympia.devhub.tasks.create_version_for_upload')
        self.create_version_for_upload = patcher.start()
        self.addCleanup(patcher.stop)

    def create_upload(self, version='1.0'):
        return FileUpload.objects.create(
            addon=self.addon, version=version, validation='{"errors":0}',
            automated_signing=self.addon.automated_signing)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations(self):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk)
        self.create_version_for_upload.assert_called_with(self.addon, upload)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations',
                False)
    def test_file_not_passed_all_validations(self):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk)
        assert not self.create_version_for_upload.called


class TestCreateVersionForUpload(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCreateVersionForUpload, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.create_version_for_upload = (
            tasks.create_version_for_upload.non_atomic)
        patcher = mock.patch('olympia.devhub.tasks.Version.from_upload')
        self.version__from_upload = patcher.start()
        self.addCleanup(patcher.stop)

    def create_upload(self, version='1.0'):
        return FileUpload.objects.create(
            addon=self.addon, version=version, validation='{"errors":0}',
            automated_signing=self.addon.automated_signing)

    def test_file_passed_all_validations_not_most_recent(self):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # Check that the older file won't turn into a Version.
        self.create_version_for_upload(self.addon, upload)
        assert not self.version__from_upload.called

        # But the newer one will.
        self.create_version_for_upload(self.addon, newer_upload)
        self.version__from_upload.assert_called_with(
            newer_upload, self.addon, [amo.PLATFORM_ALL.id], is_beta=False)

    def test_file_passed_all_validations_version_exists(self):
        upload = self.create_upload()
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        self.create_version_for_upload(self.addon, upload)
        assert not self.version__from_upload.called

    def test_file_passed_all_validations_most_recent_failed(self):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1),
                            valid=False,
                            validation=json.dumps({"errors": 5}))

        self.create_version_for_upload(self.addon, upload)
        assert not self.version__from_upload.called

    def test_file_passed_all_validations_most_recent(self):
        upload = self.create_upload(version='1.0')
        newer_upload = self.create_upload(version='0.5')
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # The Version is created because the newer upload is for a different
        # version_string.
        self.create_version_for_upload(self.addon, upload)
        self.version__from_upload.assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id], is_beta=False)

    def test_file_passed_all_validations_beta(self):
        upload = self.create_upload(version='1.0-beta1')
        self.create_version_for_upload(self.addon, upload)
        self.version__from_upload.assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id], is_beta=True)

    def test_file_passed_all_validations_no_version(self):
        upload = self.create_upload(version=None)
        self.create_version_for_upload(self.addon, upload)
        self.version__from_upload.assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id], is_beta=False)
