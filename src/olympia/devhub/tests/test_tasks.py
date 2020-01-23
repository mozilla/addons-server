# -*- coding: utf-8 -*-
import json
import os
import shutil
import tempfile

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage

from unittest import mock
import pytest

from PIL import Image

from olympia import amo
from olympia.addons.models import Addon, AddonUser, Preview
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.tests.test_helpers import get_addon_file, get_image_path
from olympia.amo.utils import image_size, utc_millesecs_from_epoch
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.applications.models import AppVersion
from olympia.constants.base import VALIDATOR_SKELETON_RESULTS
from olympia.devhub import tasks
from olympia.files.models import File
from olympia.files.utils import NoManifestFound
from olympia.files.tests.test_models import UploadTest
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


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

    src = tempfile.NamedTemporaryFile(
        mode='r+b', suffix='.png', delete=False, dir=settings.TMP_PATH)

    if not isinstance(final_size, list):
        final_size = [final_size]
        resize_size = [resize_size]
    uploadto = user_media_path('addon_icons')
    try:
        os.makedirs(uploadto)
    except OSError:
        pass
    for rsize, expected_size in zip(resize_size, final_size):
        # resize_icon moves the original
        shutil.copyfile(img, src.name)
        src_image = Image.open(src.name)
        assert src_image.size == original_size
        dest_name = os.path.join(uploadto, '1234')

        with mock.patch('olympia.amo.utils.pngcrush_image') as pngcrush_mock:
            return_value = tasks.resize_icon(src.name, dest_name, [rsize])
        dest_image = '%s-%s.png' % (dest_name, rsize)
        assert pngcrush_mock.call_count == 1
        assert pngcrush_mock.call_args_list[0][0][0] == dest_image
        assert image_size(dest_image) == expected_size
        # original should have been moved to -original
        orig_image = '%s-original.png' % dest_name
        assert os.path.exists(orig_image)

        # Return value of the task should be a dict with an icon_hash key
        # containing the 8 first chars of the md5 hash of the source file,
        # which is bb362450b00f0461c6bddc6b97b3c30b.
        assert return_value == {'icon_hash': 'bb362450'}

        os.remove(dest_image)
        assert not os.path.exists(dest_image)
        os.remove(orig_image)
        assert not os.path.exists(orig_image)
    shutil.rmtree(uploadto)

    assert not os.path.exists(src.name)


@pytest.mark.django_db
@mock.patch('olympia.amo.utils.pngcrush_image')
def test_recreate_previews(pngcrush_image_mock):
    addon = addon_factory()
    # Set up the preview so it has files in the right places.
    preview_no_original = Preview.objects.create(addon=addon)
    with storage.open(preview_no_original.image_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg'), 'rb'),
                           dest)
    with storage.open(preview_no_original.thumbnail_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png'), 'rb'), dest)
    # And again but this time with an "original" image.
    preview_has_original = Preview.objects.create(addon=addon)
    with storage.open(preview_has_original.image_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg'), 'rb'),
                           dest)
    with storage.open(preview_has_original.thumbnail_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png'), 'rb'), dest)
    with storage.open(preview_has_original.original_path, 'wb') as dest:
        shutil.copyfileobj(open(get_image_path('teamaddons.jpg'), 'rb'), dest)

    tasks.recreate_previews([addon.id])

    assert preview_no_original.reload().sizes == {
        'image': [533, 400], 'thumbnail': [533, 400]}
    # Check no resize for full size, but resize happened for thumbnail
    assert (storage.size(preview_no_original.image_path) ==
            storage.size(get_image_path('preview_landscape.jpg')))
    assert (storage.size(preview_no_original.thumbnail_path) !=
            storage.size(get_image_path('mozilla.png')))

    assert preview_has_original.reload().sizes == {
        'image': [2400, 1600], 'thumbnail': [640, 427],
        'original': [3000, 2000]}
    # Check both full and thumbnail changed, but original didn't.
    assert (storage.size(preview_has_original.image_path) !=
            storage.size(get_image_path('preview_landscape.jpg')))
    assert (storage.size(preview_has_original.thumbnail_path) !=
            storage.size(get_image_path('mozilla.png')))
    assert (storage.size(preview_has_original.original_path) ==
            storage.size(get_image_path('teamaddons.jpg')))


class ValidatorTestCase(TestCase):
    def setUp(self):
        self.create_appversion('firefox', '38.0a1')

        # Required for WebExtensions tests.
        self.create_appversion('firefox', '*')
        self.create_appversion('firefox', '42.0')
        self.create_appversion('firefox', '42.*')
        self.create_appversion('firefox', '43.0')

        # Required for 57-specific tests.
        self.create_appversion('android', '38.0a1')
        self.create_appversion('android', '*')
        self.create_appversion('firefox', '57.0')

        # Required for Android tests.
        self.create_appversion('android', '42.0')
        self.create_appversion('android', '45.0')

    def create_appversion(self, name, version):
        return AppVersion.objects.create(
            application=amo.APPS[name].id, version=version)


class TestMeasureValidationTime(UploadTest, TestCase):

    def setUp(self):
        super(TestMeasureValidationTime, self).setUp()
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload = self.get_upload(
            abspath=get_addon_file('valid_webextension.xpi'),
            with_validation=False)
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

    def assert_milleseconds_are_close(self, actual_ms, calculated_ms,
                                      fuzz=None):
        if fuzz is None:
            fuzz = Decimal(300)
        assert (actual_ms >= (calculated_ms - fuzz) and
                actual_ms <= (calculated_ms + fuzz))

    def handle_upload_validation_result(self,
                                        channel=amo.RELEASE_CHANNEL_LISTED):
        results = amo.VALIDATOR_SKELETON_RESULTS.copy()
        tasks.handle_upload_validation_result(results, self.upload.pk,
                                              channel, False)

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
            'devhub.linter.results.all.success'
        )

    def test_count_all_errors(self):
        tasks.track_validation_stats(self.result(errors=1))
        self.mock_incr.assert_any_call(
            'devhub.linter.results.all.failure'
        )

    def test_count_listed_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': True}))
        self.mock_incr.assert_any_call(
            'devhub.linter.results.listed.success'
        )

    def test_count_unlisted_results(self):
        tasks.track_validation_stats(self.result(metadata={'listed': False}))
        self.mock_incr.assert_any_call(
            'devhub.linter.results.unlisted.success'
        )


class TestRunAddonsLinter(UploadTest, ValidatorTestCase):
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
             "message": "Package already signed",
             "uid": "87326f8f699f447e90b3d5a66a78513e",
             "line": None,
             "compatibility_type": None},
        ]
    })

    def setUp(self):
        super(TestRunAddonsLinter, self).setUp()

        self.valid_path = get_addon_file('valid_webextension.xpi')
        self.invalid_path = get_addon_file(
            'invalid_webextension_invalid_id.xpi')

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        assert upload.reload().valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        assert not upload.reload().valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        upload.reload()
        validation = upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == ['validator',
                                                   'unexpected_exception']
        assert not upload.valid

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_validation_signing_warning(self, _mock):
        """If we sign addons, warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        upload.reload()
        validation = json.loads(upload.validation)
        assert validation['warnings'] == 1
        assert len(validation['messages']) == 1

    @mock.patch('olympia.devhub.tasks.statsd.incr')
    def test_track_validation_stats(self, mock_statsd_incr):
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        mock_statsd_incr.assert_has_calls((
            mock.call('devhub.linter.results.all.success'),
            mock.call('devhub.linter.results.listed.success')))

    def test_handle_file_validation_result_task_result_is_serializable(self):
        addon = addon_factory()
        self.file = addon.current_version.all_files[0]
        assert not self.file.has_been_validated
        file_validation_id = tasks.validate(self.file).get()
        assert json.dumps(file_validation_id)
        # Not `self.file.reload()`. It won't update the `validation` FK.
        self.file = File.objects.get(pk=self.file.pk)
        assert self.file.has_been_validated

    def test_binary_flag_set_on_addon_for_binary_extensions(self):
        results = {
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "contains_binary_extension": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes"
            }
        }
        self.addon = addon_factory()
        self.file = self.addon.current_version.all_files[0]
        assert not self.addon.binary
        tasks.handle_file_validation_result(results, self.file.pk)
        self.addon = Addon.objects.get(pk=self.addon.pk)
        assert self.addon.binary

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_calls_run_linter(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = '{"errors": 0}'
        upload = self.get_upload(
            abspath=self.valid_path, with_validation=False)
        assert not upload.valid
        tasks.validate(upload, listed=True)
        upload.reload()
        assert upload.valid, upload.validation

    def test_run_linter_fail(self):
        upload = self.get_upload(
            abspath=self.invalid_path, with_validation=False)
        tasks.validate(upload, listed=True)
        upload.reload()
        assert not upload.valid

    def test_run_linter_path_doesnt_exist(self):
        with pytest.raises(ValueError) as exc:
            tasks.run_addons_linter('doesntexist', amo.RELEASE_CHANNEL_LISTED)

        assert str(exc.value) == (
            'Path "doesntexist" is not a file or directory or '
            'does not exist.')

    def test_run_linter_use_temporary_file(self):
        TemporaryFile = tempfile.TemporaryFile

        with mock.patch('olympia.devhub.tasks.tempfile.TemporaryFile') as tmpf:
            tmpf.side_effect = lambda *a, **kw: TemporaryFile(*a, **kw)

            # This is a relatively small add-on but we are making sure that
            # we're using a temporary file for all our linter output.
            result = json.loads(tasks.run_addons_linter(
                get_addon_file('webextension_containing_binary_files.xpi'),
                amo.RELEASE_CHANNEL_LISTED
            ))

            assert tmpf.call_count == 2
            assert result['success']
            assert not result['warnings']
            assert not result['errors']


class TestValidateFilePath(ValidatorTestCase):

    def test_success(self):
        result = json.loads(tasks.validate_file_path(
            get_addon_file('valid_webextension.xpi'),
            channel=amo.RELEASE_CHANNEL_LISTED))
        assert result['success']
        assert not result['errors']
        assert not result['warnings']

    def test_fail_warning(self):
        result = json.loads(tasks.validate_file_path(
            get_addon_file('valid_webextension_warning.xpi'),
            channel=amo.RELEASE_CHANNEL_LISTED))
        assert result['success']
        assert not result['errors']
        assert result['warnings']

    def test_fail_error(self):
        result = json.loads(tasks.validate_file_path(
            get_addon_file('invalid_webextension_invalid_id.xpi'),
            channel=amo.RELEASE_CHANNEL_LISTED))
        assert not result['success']
        assert result['errors']
        assert not result['warnings']

    @mock.patch('olympia.devhub.tasks.parse_addon')
    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_manifest_not_found_error(
            self, run_addons_linter_mock, parse_addon_mock):
        parse_addon_mock.side_effect = NoManifestFound(message=u'Fôo')
        # When parse_addon() raises a NoManifestFound error, we should
        # still call the linter to let it raise the appropriate error message.
        tasks.validate_file_path(
            get_addon_file('valid_webextension.xpi'),
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert run_addons_linter_mock.call_count == 1

    @mock.patch('olympia.devhub.tasks.parse_addon')
    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_invalid_json_manifest_error(
            self, run_addons_linter_mock, parse_addon_mock):
        parse_addon_mock.side_effect = NoManifestFound(message=u'Fôo')
        # When parse_addon() raises a InvalidManifest error, we should
        # still call the linter to let it raise the appropriate error message.
        tasks.validate_file_path(
            get_addon_file('invalid_manifest_webextension.xpi'),
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert run_addons_linter_mock.call_count == 1


class TestWebextensionIncompatibilities(UploadTest, ValidatorTestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)

        # valid_webextension.xpi has version 1.0 so mock the original version
        self.addon.update(guid='beastify@mozilla.org')
        self.addon.current_version.update(version='0.9')
        self.update_files(
            version=self.addon.current_version,
            filename='delicious_bookmarks-2.1.106-fx.xpi')

    def update_files(self, **kw):
        for version in self.addon.versions.all():
            for file in version.files.all():
                file.update(**kw)

    def test_webextension_no_webext_no_warning(self):
        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=self.addon,
            version='0.1')
        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        validation = upload.processed_validation

        expected = ['validation', 'messages', 'webext_upgrade']
        assert not any(msg['id'] == expected for msg in validation['messages'])

    def test_webextension_cannot_be_downgraded(self):
        self.update_files(is_webextension=True)

        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=self.addon)
        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'

    def test_webextension_downgrade_unlisted_error(self):
        self.update_files(is_webextension=True)
        self.make_addon_unlisted(self.addon)

        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=self.addon)
        tasks.validate(upload, listed=False)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'
        assert validation['errors'] == 1

    def test_webextension_cannot_be_downgraded_ignore_deleted_version(self):
        """Make sure even deleting the previous version does not prevent
        the downgrade error."""
        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')

        self.update_files(is_webextension=True)

        deleted_version = version_factory(
            addon=self.addon, file_kw={'is_webextension': False})
        deleted_version.delete()

        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=self.addon)
        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'legacy_addons_unsupported']

        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'


class TestLegacyAddonRestrictions(UploadTest, ValidatorTestCase):
    def test_legacy_submissions_disabled(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        upload = self.get_upload(abspath=file_, with_validation=False)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert upload.processed_validation['messages'][0]['description'] == []
        assert not upload.valid

    def test_legacy_updates_disabled(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert not upload.valid

    def test_submit_legacy_dictionary_disabled(self):
        file_ = get_addon_file('dictionary_targeting_57.xpi')
        addon = addon_factory(version_kw={'version': '0.1'},
                              type=amo.ADDON_DICT)
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert not upload.valid

    def test_submit_legacy_thunderbird_specific_message(self):
        # We only show thunderbird/seamonkey specific error message
        # if the user submits a thunderbird/seamonkey extension.
        file_ = get_addon_file('valid_firefox_and_thunderbird_addon.xpi')
        addon = addon_factory(version_kw={'version': '0.0.1'})
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert upload.processed_validation['messages'][0]['description'] == [
            u'Add-ons for Thunderbird and SeaMonkey are now listed and '
            'maintained on addons.thunderbird.net. You can use the same '
            'account to update your add-ons on the new site.']
        assert not upload.valid

    def test_submit_legacy_seamonkey_specific_message(self):
        # We only show thunderbird/seamonkey specific error message
        # if the user submits a thunderbird/seamonkey extension.
        file_ = get_addon_file('valid_seamonkey_addon.xpi')
        addon = addon_factory(version_kw={'version': '0.0.1'})
        upload = self.get_upload(
            abspath=file_, with_validation=False, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_unsupported']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert upload.processed_validation['messages'][0]['description'] == [
            u'Add-ons for Thunderbird and SeaMonkey are now listed and '
            'maintained on addons.thunderbird.net. You can use the same '
            'account to update your add-ons on the new site.']
        assert not upload.valid

    def test_submit_webextension(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(abspath=file_, with_validation=False)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_search_plugin(self):
        file_ = get_addon_file('searchgeek-20090701.xml')
        upload = self.get_upload(abspath=file_, with_validation=False)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert not upload.valid
        assert upload.processed_validation['errors'] == 1
        assert upload.processed_validation['messages'] == [{
            'compatibility_type': None,
            'description': [],
            'id': ['validation', 'messages', 'opensearch_unsupported'],
            'message': (
                'Open Search add-ons are <a '
                'href="https://blog.mozilla.org/addons/2019/10/15/'
                'search-engine-add-ons-to-be-removed-from-addons-mozilla-org/"'
                ' rel="nofollow">no longer supported on AMO</a>. You can '
                'create a <a href="https://developer.mozilla.org/docs/Mozilla'
                '/Add-ons/WebExtensions/manifest.json/'
                'chrome_settings_overrides" rel="nofollow">search extension '
                'instead</a>.'),
            'tier': 1,
            'type': 'error'}]


@mock.patch('olympia.devhub.tasks.send_html_mail_jinja')
def test_send_welcome_email(send_html_mail_jinja_mock):
    tasks.send_welcome_email(3615, ['del@icio.us'], {'omg': 'yes'})
    send_html_mail_jinja_mock.assert_called_with(
        ('Mozilla Add-ons: Your add-on has been submitted to'
         ' addons.mozilla.org!'),
        'devhub/email/submission.html',
        'devhub/email/submission.txt',
        {'omg': 'yes'},
        recipient_list=['del@icio.us'],
        from_email=settings.ADDONS_EMAIL,
        use_deny_list=False,
        perm_setting='individual_contact')


class TestSubmitFile(UploadTest, TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestSubmitFile, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        patcher = mock.patch('olympia.devhub.tasks.create_version_for_upload')
        self.create_version_for_upload = patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, addon=self.addon, version='1.0')
        tasks.submit_file(self.addon.pk, upload.pk, amo.RELEASE_CHANNEL_LISTED)
        self.create_version_for_upload.assert_called_with(
            self.addon, upload, amo.RELEASE_CHANNEL_LISTED)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations',
                False)
    def test_file_not_passed_all_validations(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, addon=self.addon, version='1.0')
        tasks.submit_file(self.addon.pk, upload.pk, amo.RELEASE_CHANNEL_LISTED)
        assert not self.create_version_for_upload.called


class TestCreateVersionForUpload(UploadTest, TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCreateVersionForUpload, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.mocks = {}
        for key in ['Version.from_upload', 'parse_addon']:
            patcher = mock.patch('olympia.devhub.tasks.%s' % key)
            self.mocks[key] = patcher.start()
            self.addCleanup(patcher.stop)
        self.user = user_factory()

    def test_file_passed_all_validations_not_most_recent(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # Check that the older file won't turn into a Version.
        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

        # But the newer one will.
        tasks.create_version_for_upload(self.addon, newer_upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        self.mocks['Version.from_upload'].assert_called_with(
            newer_upload, self.addon, [amo.FIREFOX.id, amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_version_exists(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent_failed(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        newer_upload.update(created=datetime.today() + timedelta(hours=1),
                            valid=False,
                            validation=json.dumps({"errors": 5}))

        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0')
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='0.5')
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # The Version is created because the newer upload is for a different
        # version_string.
        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.FIREFOX.id, amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_beta_string(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon,
            version='1.0beta1')
        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.FIREFOX.id, amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_no_version(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon,
            version=None)
        tasks.create_version_for_upload(self.addon, upload,
                                        amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.FIREFOX.id, amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)


class TestAPIKeyInSubmission(UploadTest, TestCase):

    def setUp(self):
        self.user = user_factory()

        s = '656b16a8ab71686fcfcd04d574bc28be9a1d8252141f54cfb5041709262b84f4'
        self.key = APIKey.objects.create(
            user=self.user,
            type=SYMMETRIC_JWT_TYPE,
            key='user:12345:678',
            secret=s)
        self.addon = addon_factory(users=[self.user],
                                   version_kw={'version': '0.1'},
                                   file_kw={'is_webextension': True})
        self.file = get_addon_file('webextension_containing_api_key.xpi')

    def test_api_key_in_new_submission_is_found(self):
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon,
            user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == [
            u'validation', u'messages', u'api_key_detected']
        assert ('Your developer API key was found in the submitted '
                'file.' in messages[0]['message'])
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert ('Your AMO API credentials have been revoked'
                in mail.outbox[0].subject)
        assert mail.outbox[0].to[0] == self.user.email

    def test_api_key_in_submission_is_found(self):
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon,
            user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == [
            u'validation', u'messages', u'api_key_detected']
        assert ('Your developer API key was found in the submitted '
                'file.' in messages[0]['message'])
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert ('Your AMO API credentials have been revoked'
                in mail.outbox[0].subject)
        assert ('never share your credentials' in mail.outbox[0].body)
        assert mail.outbox[0].to[0] == self.user.email

    def test_coauthor_api_key_in_submission_is_found(self):
        coauthor = user_factory()
        AddonUser.objects.create(addon=self.addon, user_id=coauthor.id)
        upload = self.get_upload(
            abspath=self.file, with_validation=False, addon=self.addon,
            user=coauthor)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['id'] == [
            u'validation', u'messages', u'api_key_detected']
        assert ('The developer API key of a coauthor was found in the '
                'submitted file.' in messages[0]['message'])
        assert not upload.valid

        # If the key has been revoked, there is no active key,
        # so `get_jwt_key` raises `DoesNotExist`.
        with pytest.raises(APIKey.DoesNotExist):
            APIKey.get_jwt_key(user_id=self.user.id)

        assert len(mail.outbox) == 1
        assert ('Your AMO API credentials have been revoked'
                in mail.outbox[0].subject)
        assert ('never share your credentials' in mail.outbox[0].body)
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
                abspath=self.file, with_validation=False, user=self.user)
            tasks.validate(upload, listed=True)
            upload.refresh_from_db()
            mock_revoke.apply_async.assert_called_with(
                kwargs={'key_id': self.key.id}, countdown=120)

        assert not upload.valid

    def test_does_not_revoke_for_different_author(self):
        different_author = user_factory()
        upload = self.get_upload(
            abspath=self.file, with_validation=False, user=different_author)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.valid

    def test_does_not_revoke_safe_webextension(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_binary_content(self):
        file_ = get_addon_file('webextension_containing_binary_files.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_invalid_filename(self):
        file_ = get_addon_file('invalid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, with_validation=False, user=self.user)
        tasks.validate(upload, listed=True)

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
