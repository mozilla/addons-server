import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

import pytest
from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import Addon, AddonUser, Preview
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, root_storage, user_factory
from olympia.amo.tests.test_helpers import get_addon_file, get_image_path
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.applications.models import AppVersion
from olympia.constants.base import VALIDATOR_SKELETON_RESULTS
from olympia.devhub import tasks
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import NoManifestFound


pytestmark = pytest.mark.django_db


@pytest.mark.django_db
@mock.patch('olympia.amo.utils.pngcrush_image')
def test_recreate_previews(pngcrush_image_mock):
    addon = addon_factory()
    # Set up the preview so it has files in the right places.
    preview_no_original = Preview.objects.create(addon=addon)
    with root_storage.open(preview_no_original.image_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg'), 'rb'), dest)
    with root_storage.open(preview_no_original.thumbnail_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png'), 'rb'), dest)
    # And again but this time with an "original" image.
    preview_has_original = Preview.objects.create(addon=addon)
    with root_storage.open(preview_has_original.image_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg'), 'rb'), dest)
    with root_storage.open(preview_has_original.thumbnail_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png'), 'rb'), dest)
    with root_storage.open(preview_has_original.original_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('teamaddons.jpg'), 'rb'), dest)

    tasks.recreate_previews([addon.id])

    assert preview_no_original.reload().sizes == {
        'image': [533, 400],
        'thumbnail': [533, 400],
        'thumbnail_format': 'jpg',
    }
    # Check no resize for full size, but resize happened for thumbnail
    assert root_storage.size(preview_no_original.image_path) == root_storage.size(
        get_image_path('preview_landscape.jpg')
    )
    assert root_storage.size(preview_no_original.thumbnail_path) != root_storage.size(
        get_image_path('mozilla.png')
    )
    assert root_storage.size(preview_no_original.thumbnail_path) > 0

    assert preview_has_original.reload().sizes == {
        'image': [2400, 1600],
        'thumbnail': [533, 355],
        'original': [3000, 2000],
        'thumbnail_format': 'jpg',
    }
    # Check both full and thumbnail changed, but original didn't.
    assert root_storage.size(preview_has_original.image_path) != root_storage.size(
        get_image_path('preview_landscape.jpg')
    )
    assert root_storage.size(preview_has_original.thumbnail_path) != root_storage.size(
        get_image_path('mozilla.png')
    )
    assert root_storage.size(preview_has_original.thumbnail_path) > 0
    assert root_storage.size(preview_has_original.original_path) == root_storage.size(
        get_image_path('teamaddons.jpg')
    )


class ValidatorTestCase(TestCase):
    def setUp(self):
        # Required for WebExtensions tests.
        self.create_appversion('firefox', '*')
        self.create_appversion('android', '*')
        self.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION)
        self.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION)

    def create_appversion(self, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id, version=version)


class TestMeasureValidationTime(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload = self.get_upload(
            abspath=get_addon_file('valid_webextension.xpi'), with_validation=False
        )
        assert not self.upload.valid

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

    def assert_milleseconds_are_close(self, actual_ms, calculated_ms, fuzz=None):
        if fuzz is None:
            fuzz = Decimal(300)
        assert actual_ms >= (calculated_ms - fuzz) and actual_ms <= (
            calculated_ms + fuzz
        )

    def handle_upload_validation_result(self):
        results = amo.VALIDATOR_SKELETON_RESULTS.copy()
        tasks.handle_upload_validation_result(results, self.upload.pk, False)

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
        actual_delta = statsd_calls['devhub.validation_results_processed_per_mb']
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
        actual_scaled_delta = statsd_calls['devhub.validation_results_processed_per_mb']
        self.assert_milleseconds_are_close(actual_scaled_delta, rough_scaled_delta)

    def test_measure_small_files_in_separate_bucket(self):
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = 500  # less than 1MB
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls['devhub.validation_results_processed_under_1mb']
        self.assert_milleseconds_are_close(actual_delta, rough_delta)

    def test_measure_large_files_in_separate_bucket(self):
        with mock.patch('olympia.devhub.tasks.storage.size') as mock_size:
            mock_size.return_value = (2014 * 1024) * 5  # 5MB
            with self.statsd_timing_mock() as statsd_calls:
                self.handle_upload_validation_result()

        rough_delta = self.approximate_upload_time()
        actual_delta = statsd_calls['devhub.validation_results_processed_over_1mb']
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
        assert 'devhub.validation_results_processed_under_1mb' not in statsd_calls


class TestTrackValidatorStats(TestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch('olympia.devhub.tasks.statsd.incr')
        self.mock_incr = patch.start()
        self.addCleanup(patch.stop)

    def result(self, **overrides):
        result = VALIDATOR_SKELETON_RESULTS.copy()
        result.update(overrides)
        return result

    def test_count_all_successes(self):
        tasks.track_validation_stats(self.result(errors=0))
        self.mock_incr.assert_any_call('devhub.linter.results.all.success')

    def test_count_all_errors(self):
        tasks.track_validation_stats(self.result(errors=1))
        self.mock_incr.assert_any_call('devhub.linter.results.all.failure')

    def test_count_listed_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': True}))
        self.mock_incr.assert_any_call('devhub.linter.results.listed.success')

    def test_count_unlisted_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': False}))
        self.mock_incr.assert_any_call('devhub.linter.results.unlisted.success')


class TestRunAddonsLinter(UploadMixin, ValidatorTestCase):
    mock_sign_addon_warning = {
        'warnings': 1,
        'errors': 0,
        'messages': [
            {
                'context': None,
                'editors_only': False,
                'description': 'Add-ons which are already signed will be '
                're-signed when published on AMO. This will '
                'replace any existing signatures on the add-on.',
                'column': None,
                'type': 'warning',
                'id': ['testcases_content', 'signed_xpi'],
                'file': '',
                'tier': 2,
                'message': 'Package already signed',
                'uid': '87326f8f699f447e90b3d5a66a78513e',
                'line': None,
                'compatibility_type': None,
            },
        ],
    }

    def setUp(self):
        super().setUp()

        self.valid_path = get_addon_file('valid_webextension.xpi')
        self.invalid_path = get_addon_file('invalid_webextension_invalid_id.xpi')

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_pass_validation(self, _mock):
        _mock.return_value = {'errors': 0}
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        tasks.validate(upload)
        assert upload.reload().valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_fail_validation(self, _mock):
        _mock.return_value = {'errors': 2}
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        tasks.validate(upload)
        assert not upload.reload().valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        tasks.validate(upload)
        upload.reload()
        validation = upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == ['validator', 'unexpected_exception']
        assert not upload.valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validation_signing_warning(self, _mock):
        """If we sign addons, warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        tasks.validate(upload)
        upload.reload()
        validation = json.loads(upload.validation)
        assert validation['warnings'] == 1
        assert len(validation['messages']) == 1

    @mock.patch('olympia.devhub.tasks.statsd.incr')
    def test_track_validation_stats(self, mock_statsd_incr):
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        tasks.validate(upload)
        mock_statsd_incr.assert_has_calls(
            (
                mock.call('devhub.linter.results.all.success'),
                mock.call('devhub.linter.results.listed.success'),
            )
        )

    def test_handle_file_validation_result_task_result_is_serializable(self):
        addon = addon_factory()
        self.file = addon.current_version.file
        assert not self.file.has_been_validated
        file_validation_id = tasks.validate(self.file).get()
        assert json.dumps(file_validation_id)
        # Not `self.file.reload()`. It won't update the `validation` FK.
        self.file = File.objects.get(pk=self.file.pk)
        assert self.file.has_been_validated

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_calls_run_linter(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = {'errors': 0}
        upload = self.get_upload(abspath=self.valid_path, with_validation=False)
        assert not upload.valid
        tasks.validate(upload)
        upload.reload()
        assert upload.valid, upload.validation

    def test_run_linter_fail(self):
        upload = self.get_upload(abspath=self.invalid_path, with_validation=False)
        tasks.validate(upload)
        upload.reload()
        assert not upload.valid

    def test_run_linter_path_doesnt_exist(self):
        with pytest.raises(ValueError) as exc:
            tasks.run_addons_linter('doesntexist', amo.CHANNEL_LISTED)

        assert str(exc.value) == (
            'Path "doesntexist" is not a file or directory or does not exist.'
        )

    def test_run_linter_use_temporary_file(self):
        TemporaryFile = tempfile.TemporaryFile

        with mock.patch('olympia.devhub.tasks.tempfile.TemporaryFile') as tmpf:
            tmpf.side_effect = lambda *a, **kw: TemporaryFile(*a, **kw)

            # This is a relatively small add-on but we are making sure that
            # we're using a temporary file for all our linter output.
            result = tasks.run_addons_linter(
                get_addon_file('webextension_containing_binary_files.xpi'),
                amo.CHANNEL_LISTED,
            )

            assert tmpf.call_count == 2
            assert result['success']
            assert not result['warnings']
            assert not result['errors']

    class FakePopen:
        """This is a fake implementation that is used to simulate the linter
        execution and record the arguments used to execute it."""

        args = None

        def __init__(self, args, stdout, stderr, shell):
            self.stdout = stdout
            self.set_args(args)

        def wait(self):
            # Write something to stdout to simulate the linter execution.
            self.stdout.write(
                b'{"errors": [], "notices": [], "warnings": [],'
                b'"metadata": {}, "summary": {"notices": 0, "warnings": 0,'
                b' "errors": 0}}'
            )

        @classmethod
        def set_args(cls, args):
            cls.args = args

        @classmethod
        def get_args(cls):
            return cls.args

    @override_switch('disable-linter-xpi-autoclose', active=True)
    @mock.patch('olympia.devhub.tasks.subprocess')
    def test_xpi_autoclose_is_disabled(self, subprocess_mock):
        subprocess_mock.Popen = self.FakePopen

        tasks.run_addons_linter(path=self.valid_path, channel=amo.CHANNEL_LISTED)

        assert '--disable-xpi-autoclose' in self.FakePopen.get_args()

    @override_switch('disable-linter-xpi-autoclose', active=False)
    @mock.patch('olympia.devhub.tasks.subprocess')
    def test_xpi_autoclose_is_enabled(self, subprocess_mock):
        subprocess_mock.Popen = self.FakePopen

        tasks.run_addons_linter(path=self.valid_path, channel=amo.CHANNEL_LISTED)

        assert '--disable-xpi-autoclose' not in self.FakePopen.get_args()

    @override_switch('enable-mv3-submissions', active=False)
    def test_mv3_submissions_waffle_disabled(self):
        with mock.patch('olympia.devhub.tasks.subprocess') as subprocess_mock:
            subprocess_mock.Popen = self.FakePopen

            tasks.run_addons_linter(path=self.valid_path, channel=amo.CHANNEL_LISTED)

            assert '--max-manifest-version=3' not in self.FakePopen.get_args()
            assert '--max-manifest-version=2' in self.FakePopen.get_args()

        mv3_path = get_addon_file('webextension_mv3.xpi')
        result = tasks.run_addons_linter(mv3_path, channel=amo.CHANNEL_LISTED)
        assert result.get('errors') == 1

    @override_switch('enable-mv3-submissions', active=True)
    def test_mv3_submission_enabled(self):
        with mock.patch('olympia.devhub.tasks.subprocess') as subprocess_mock:
            subprocess_mock.Popen = self.FakePopen

            tasks.run_addons_linter(path=self.valid_path, channel=amo.CHANNEL_LISTED)

            assert '--max-manifest-version=3' in self.FakePopen.get_args()
            assert '--max-manifest-version=2' not in self.FakePopen.get_args()

        mv3_path = get_addon_file('webextension_mv3.xpi')
        result = tasks.run_addons_linter(mv3_path, channel=amo.CHANNEL_LISTED)
        assert result.get('errors') == 0

        # double check v2 manifests still work
        result = tasks.run_addons_linter(self.valid_path, channel=amo.CHANNEL_LISTED)
        assert result.get('errors') == 0

    def test_enable_background_service_worker_setting(self):
        flag = '--enable-background-service-worker'
        with mock.patch('olympia.devhub.tasks.subprocess') as subprocess_mock:
            subprocess_mock.Popen = self.FakePopen

            with override_settings(ADDONS_LINTER_ENABLE_SERVICE_WORKER=False):
                tasks.run_addons_linter(
                    path=self.valid_path, channel=amo.CHANNEL_LISTED
                )
                assert flag not in self.FakePopen.get_args()

            with override_settings(ADDONS_LINTER_ENABLE_SERVICE_WORKER=True):
                tasks.run_addons_linter(
                    path=self.valid_path, channel=amo.CHANNEL_LISTED
                )
                assert flag in self.FakePopen.get_args()


class TestValidateFilePath(ValidatorTestCase):
    def copy_addon_file(self, name):
        """Copy addon file from our test files to storage location and return
        new path under that location so that it can be opened by
        storage.open()."""
        dest_path = storage.path('files/temp/webextension.xpi')
        self.root_storage.copy_stored_file(get_addon_file(name), dest_path)
        return dest_path

    def test_success(self):
        result = json.loads(
            tasks.validate_file_path(
                self.copy_addon_file('valid_webextension.xpi'),
                channel=amo.CHANNEL_LISTED,
            )
        )
        assert result['success']
        assert not result['errors']
        assert not result['warnings']

    def test_fail_warning(self):
        result = json.loads(
            tasks.validate_file_path(
                self.copy_addon_file('valid_webextension_warning.xpi'),
                channel=amo.CHANNEL_LISTED,
            )
        )
        assert result['success']
        assert not result['errors']
        assert result['warnings']

    def test_fail_error(self):
        result = json.loads(
            tasks.validate_file_path(
                self.copy_addon_file('invalid_webextension_invalid_id.xpi'),
                channel=amo.CHANNEL_LISTED,
            )
        )
        assert not result['success']
        assert result['errors']
        assert not result['warnings']

    @mock.patch('olympia.devhub.tasks.parse_addon')
    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_manifest_not_found_error(self, run_addons_linter_mock, parse_addon_mock):
        parse_addon_mock.side_effect = NoManifestFound(message='Fôo')
        run_addons_linter_mock.return_value = {}
        # When parse_addon() raises a NoManifestFound error, we should
        # still call the linter to let it raise the appropriate error message.
        tasks.validate_file_path(
            self.copy_addon_file('valid_webextension.xpi'),
            channel=amo.CHANNEL_LISTED,
        )
        assert run_addons_linter_mock.call_count == 1

    @mock.patch('olympia.devhub.tasks.parse_addon')
    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_invalid_json_manifest_error(
        self, run_addons_linter_mock, parse_addon_mock
    ):
        parse_addon_mock.side_effect = NoManifestFound(message='Fôo')
        run_addons_linter_mock.return_value = {}
        # When parse_addon() raises a InvalidManifest error, we should
        # still call the linter to let it raise the appropriate error message.
        tasks.validate_file_path(
            self.copy_addon_file('invalid_manifest_webextension.xpi'),
            channel=amo.CHANNEL_LISTED,
        )
        assert run_addons_linter_mock.call_count == 1

    @mock.patch('olympia.devhub.tasks.annotations.annotate_validation_results')
    @mock.patch('olympia.devhub.tasks.parse_addon')
    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validate_file_path_mocks(
        self, run_addons_linter_mock, parse_addon_mock, annotate_validation_results_mock
    ):
        parse_addon_mock.return_value = mock.Mock()
        run_addons_linter_mock.return_value = {'fake_results': True}
        tasks.validate_file_path(
            self.copy_addon_file('valid_webextension.xpi'),
            channel=amo.CHANNEL_UNLISTED,
        )
        assert parse_addon_mock.call_count == 1
        assert run_addons_linter_mock.call_count == 1
        assert annotate_validation_results_mock.call_count == 1
        annotate_validation_results_mock.assert_called_with(
            results=run_addons_linter_mock.return_value,
            parsed_data=parse_addon_mock.return_value,
            channel=amo.CHANNEL_UNLISTED,
        )


class TestInitialSubmissionAcknoledgementEmail(TestCase):
    @mock.patch('olympia.devhub.tasks.send_html_mail_jinja')
    def test_send_with_mock(self, send_html_mail_jinja_mock):
        addon = addon_factory()
        tasks.send_initial_submission_acknowledgement_email(
            addon.pk, amo.CHANNEL_LISTED, 'del@icio.us'
        )
        send_html_mail_jinja_mock.assert_called_with(
            f'Mozilla Add-ons: {addon.name} has been submitted to addons.mozilla.org!',
            'devhub/emails/submission.html',
            'devhub/emails/submission.txt',
            {
                'addon_name': str(addon.name),
                'app': str(amo.FIREFOX.pretty),
                'listed': True,
                'detail_url': absolutify(addon.get_url_path()),
            },
            recipient_list=['del@icio.us'],
            from_email=settings.ADDONS_EMAIL,
            use_deny_list=False,
            perm_setting='individual_contact',
        )

    def test_send_email(self):
        addon = addon_factory()
        tasks.send_initial_submission_acknowledgement_email(
            addon.pk, amo.CHANNEL_LISTED, 'someone@somewhere.com'
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to[0] == 'someone@somewhere.com'
        assert mail.outbox[0].subject == (
            f'Mozilla Add-ons: {addon.name} has been submitted to addons.mozilla.org!'
        )
        text_body = mail.outbox[0].body
        assert 'your add-on listing will appear on our website' in text_body
        assert f'Thanks for submitting your {addon.name} add-on' in text_body
        assert 'http://testserver/en-US/firefox/addon/' in text_body
        assert mail.outbox[0].alternatives
        html_body, content_type = mail.outbox[0].alternatives[0]
        assert content_type == 'text/html'
        assert f'Thanks for submitting your {addon.name} add-on' in html_body
        assert 'your add-on listing will appear on our website' in html_body
        assert 'http://testserver/en-US/firefox/addon/' in html_body

    def test_send_email_unlisted(self):
        addon = addon_factory(version_kw={'channel': amo.CHANNEL_UNLISTED})
        tasks.send_initial_submission_acknowledgement_email(
            addon.pk, amo.CHANNEL_UNLISTED, 'someone@somewhere.com'
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to[0] == 'someone@somewhere.com'
        assert mail.outbox[0].subject == (
            f'Mozilla Add-ons: {addon.name} has been submitted to addons.mozilla.org!'
        )
        text_body = mail.outbox[0].body
        assert f'Thanks for submitting your {addon.name} add-on' in text_body
        assert 'your add-on listing will appear on our website' not in text_body
        assert 'http://testserver/en-US/firefox/addon/' not in text_body
        assert mail.outbox[0].alternatives
        html_body, content_type = mail.outbox[0].alternatives[0]
        assert content_type == 'text/html'
        assert f'Thanks for submitting your {addon.name} add-on' in html_body
        assert 'your add-on listing will appear on our website' not in html_body
        assert 'http://testserver/en-US/firefox/addon/' not in html_body

    def test_dont_send_addon_doesnotexist(self):
        tasks.send_initial_submission_acknowledgement_email(
            424242, amo.CHANNEL_UNLISTED, 'someone@somewhere.com'
        )
        assert len(mail.outbox) == 0

    def test_urls_locale_prefix(self):
        addon = addon_factory(default_locale='pt-BR')
        tasks.send_initial_submission_acknowledgement_email(
            addon.pk, amo.CHANNEL_LISTED, 'someone@somewhere.com'
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to[0] == 'someone@somewhere.com'
        assert mail.outbox[0].subject == (
            f'Mozilla Add-ons: {addon.name} has been submitted to addons.mozilla.org!'
        )
        text_body = mail.outbox[0].body
        assert 'your add-on listing will appear on our website' in text_body
        assert f'Thanks for submitting your {addon.name} add-on' in text_body
        assert 'http://testserver/pt-BR/firefox/addon/' in text_body
        assert mail.outbox[0].alternatives
        html_body, content_type = mail.outbox[0].alternatives[0]
        assert content_type == 'text/html'
        assert f'Thanks for submitting your {addon.name} add-on' in html_body
        assert 'your add-on listing will appear on our website' in html_body
        assert 'http://testserver/pt-BR/firefox/addon/' in html_body


class TestSubmitFile(UploadMixin, TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        patcher = mock.patch('olympia.devhub.utils.create_version_for_upload')
        self.create_version_for_upload = patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(abspath=file_, addon=self.addon, version='1.0')
        tasks.submit_file(addon_pk=self.addon.pk, upload_pk=upload.pk, client_info=None)
        self.create_version_for_upload.assert_called_with(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations_unlisted(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, addon=self.addon, version='1.0', channel=amo.CHANNEL_UNLISTED
        )
        tasks.submit_file(addon_pk=self.addon.pk, upload_pk=upload.pk, client_info=None)
        self.create_version_for_upload.assert_called_with(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_UNLISTED,
            client_info=None,
        )

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', False)
    def test_file_not_passed_all_validations(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(abspath=file_, addon=self.addon, version='1.0')
        tasks.submit_file(addon_pk=self.addon.pk, upload_pk=upload.pk, client_info=None)
        assert not self.create_version_for_upload.called


class TestAPIKeyInSubmission(UploadMixin, TestCase):
    def setUp(self):
        self.user = user_factory()

        s = '656b16a8ab71686fcfcd04d574bc28be9a1d8252141f54cfb5041709262b84f4'
        self.key = APIKey.objects.create(
            user=self.user, type=SYMMETRIC_JWT_TYPE, key='user:12345:678', secret=s
        )
        self.addon = addon_factory(
            users=[self.user],
            version_kw={'version': '0.1'},
        )
        self.file = get_addon_file('webextension_containing_api_key.xpi')

    def test_api_key_in_new_submission_is_found(self):
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon, user=self.user
        )
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == ['validation', 'messages', 'api_key_detected']
        assert (
            'Your developer API key was found in the submitted '
            'file.' in messages[0]['message']
        )
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert 'Your AMO API credentials have been revoked' in mail.outbox[0].subject
        assert mail.outbox[0].to[0] == self.user.email

    def test_api_key_in_submission_is_found(self):
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon, user=self.user
        )
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == ['validation', 'messages', 'api_key_detected']
        assert (
            'Your developer API key was found in the submitted '
            'file.' in messages[0]['message']
        )
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert 'Your AMO API credentials have been revoked' in mail.outbox[0].subject
        assert 'never share your credentials' in mail.outbox[0].body
        assert mail.outbox[0].to[0] == self.user.email

    def test_coauthor_api_key_in_submission_is_found(self):
        coauthor = user_factory()
        AddonUser.objects.create(addon=self.addon, user_id=coauthor.id)
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon, user=coauthor
        )
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == ['validation', 'messages', 'api_key_detected']
        assert (
            'The developer API key of a coauthor was found in the '
            'submitted file.' in messages[0]['message']
        )
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert 'Your AMO API credentials have been revoked' in mail.outbox[0].subject
        assert 'never share your credentials' in mail.outbox[0].body
        # We submit as the coauthor, the leaked key is the one from 'self.user'
        assert mail.outbox[0].to[0] == self.user.email

    def test_api_key_already_revoked_by_developer(self):
        self.key.update(is_active=None)
        tasks.revoke_api_key(self.key.id)
        # If the key has already been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

    def test_api_key_already_regenerated_by_developer(self):
        self.key.update(is_active=None)
        current_key = APIKey.new_jwt_credentials(user=self.user)
        tasks.revoke_api_key(self.key.id)
        key_from_db = APIKey.get_jwt_key(user_id=self.user.id)
        assert current_key.key == key_from_db.key
        assert current_key.secret == key_from_db.secret

    def test_revoke_task_is_called(self):
        mock_str = 'olympia.devhub.tasks.revoke_api_key'
        wrapped = tasks.revoke_api_key
        with mock.patch(mock_str, wraps=wrapped) as mock_revoke:
            upload = self.get_upload(
                abspath=self.file, with_validation=False, user=self.user
            )
            tasks.validate(upload)
            upload.refresh_from_db()
            mock_revoke.apply_async.assert_called_with(
                kwargs={'key_id': self.key.id}, countdown=120
            )

        assert not upload.valid

    def test_does_not_revoke_for_different_author(self):
        different_author = user_factory()
        upload = self.get_upload(
            abspath=self.file, with_validation=False, user=different_author
        )
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.valid

    def test_does_not_revoke_safe_webextension(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_binary_content(self):
        file_ = get_addon_file('webextension_containing_binary_files.xpi')
        upload = self.get_upload(abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_invalid_filename(self):
        file_ = get_addon_file('invalid_webextension.xpi')
        upload = self.get_upload(abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload)

        upload.refresh_from_db()

        # https://github.com/mozilla/addons-server/issues/8208
        # causes this to be 1 (and invalid) instead of 0 (and valid).
        # The invalid filename error is caught and raised outside of this
        # validation task.
        assert upload.processed_validation['errors'] == 1
        assert not upload.valid


class TestValidationTask(TestCase):
    def setUp(self):
        TestValidationTask.fake_task_has_been_called = False

    @tasks.validation_task
    def fake_task(results, pk):
        TestValidationTask.fake_task_has_been_called = True
        return {**results, 'fake_task_results': 1}

    def test_returns_validator_results_when_received_results_is_none(self):
        results = self.fake_task(None, 123)
        assert not self.fake_task_has_been_called
        assert results == amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT

    def test_returns_results_when_received_results_have_errors(self):
        results = {'errors': 1}
        returned_results = self.fake_task(results, 123)
        assert not self.fake_task_has_been_called
        assert results == returned_results

    def test_runs_wrapped_task(self):
        results = {'errors': 0}
        returned_results = self.fake_task(results, 123)
        assert TestValidationTask.fake_task_has_been_called
        assert results != returned_results
        assert 'fake_task_results' in returned_results


class TestForwardLinterResults(TestCase):
    def test_returns_received_results(self):
        results = {'errors': 1}
        returned_results = tasks.forward_linter_results(results, 123)
        assert results == returned_results
