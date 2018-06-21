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

import mock
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
from olympia.files.models import FileUpload
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
        mode='r+w+b', suffix='.png', delete=False, dir=settings.TMP_PATH)

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
    with storage.open(preview_no_original.image_path, 'w') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg')), dest)
    with storage.open(preview_no_original.thumbnail_path, 'w') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png')), dest)
    # And again but this time with an "original" image.
    preview_has_original = Preview.objects.create(addon=addon)
    with storage.open(preview_has_original.image_path, 'w') as dest:
        shutil.copyfileobj(open(get_image_path('preview_landscape.jpg')), dest)
    with storage.open(preview_has_original.thumbnail_path, 'w') as dest:
        shutil.copyfileobj(open(get_image_path('mozilla.png')), dest)
    with storage.open(preview_has_original.original_path, 'w') as dest:
        shutil.copyfileobj(open(get_image_path('teamaddons.jpg')), dest)

    tasks.recreate_previews([addon.id])

    assert preview_no_original.reload().sizes == {
        'image': [533, 400], 'thumbnail': [267, 200]}
    # Check no resize for full size, but resize happened for thumbnail
    assert (storage.size(preview_no_original.image_path) ==
            storage.size(get_image_path('preview_landscape.jpg')))
    assert (storage.size(preview_no_original.thumbnail_path) !=
            storage.size(get_image_path('mozilla.png')))

    assert preview_has_original.reload().sizes == {
        'image': [1200, 800], 'thumbnail': [300, 200],
        'original': [1500, 1000]}
    # Check both full and thumbnail changed, but original didn't.
    assert (storage.size(preview_has_original.image_path) !=
            storage.size(get_image_path('preview_landscape.jpg')))
    assert (storage.size(preview_has_original.thumbnail_path) !=
            storage.size(get_image_path('mozilla.png')))
    assert (storage.size(preview_has_original.original_path) ==
            storage.size(get_image_path('teamaddons.jpg')))


class ValidatorTestCase(TestCase):
    def setUp(self):
        # Because the validator calls dump_apps() once and then uses the json
        # file to find out which appversions are valid, all tests running the
        # validator need to create *all* possible appversions all tests using
        # this class might need.

        # 3.7a1pre is somehow required to exist by
        # amo-validator.
        # The other ones are app-versions we're using in our
        # tests.
        self.create_appversion('firefox', '2.0')
        self.create_appversion('firefox', '3.6')
        self.create_appversion('firefox', '3.7a1pre')
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

        # Required for Thunderbird tests.
        self.create_appversion('thunderbird', '42.0')
        self.create_appversion('thunderbird', '45.0')

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
        tasks.validate(self.upload, listed=True)
        assert self.get_upload().valid

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        tasks.validate(self.upload, listed=True)
        assert not self.get_upload().valid

    @mock.patch('validator.submain.test_package')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception

        self.upload.update(path=get_addon_file('desktop.xpi'))

        assert self.upload.validation is None

        tasks.validate(self.upload, listed=True)
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

        tasks.validate(self.upload, listed=True)
        self.upload.reload()
        validation = self.upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == [
            'validator', 'unexpected_exception']
        assert 'WebExtension' in validation['messages'][0]['message']
        assert not self.upload.valid

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_validation_signing_warning(self, _mock):
        """If we sign addons, warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        tasks.validate(self.upload, listed=True)
        validation = json.loads(self.get_upload().validation)
        assert validation['warnings'] == 1
        assert len(validation['messages']) == 1

    @mock.patch('validator.validate.validate')
    @mock.patch('olympia.devhub.tasks.track_validation_stats')
    def test_track_validation_stats(self, mock_track, mock_validate):
        mock_validate.return_value = '{"errors": 0}'
        tasks.validate(self.upload, listed=True)
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
                                      fuzz=None):
        if fuzz is None:
            fuzz = Decimal(300)
        assert (actual_ms >= (calculated_ms - fuzz) and
                actual_ms <= (calculated_ms + fuzz))

    def handle_upload_validation_result(self,
                                        channel=amo.RELEASE_CHANNEL_LISTED):
        validation = amo.VALIDATOR_SKELETON_RESULTS.copy()
        tasks.handle_upload_validation_result(validation, self.upload.pk,
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

        tasks.validate(self.valid_upload, listed=True)

        upload = self.get_upload(self.valid_upload)
        assert upload.valid, upload.validation

    def test_run_linter_fail(self):
        tasks.validate(self.invalid_upload, listed=True)
        assert not self.get_upload(self.invalid_upload).valid

    def test_run_linter_path_doesnt_exist(self):
        with pytest.raises(ValueError) as exc:
            tasks.run_addons_linter('doesntexist')

        assert str(exc.value) == (
            'Path "doesntexist" is not a file or directory or '
            'does not exist.')

    def test_run_linter_use_temporary_file(self):
        TemporaryFile = tempfile.TemporaryFile

        with mock.patch('olympia.devhub.tasks.tempfile.TemporaryFile') as tmpf:
            tmpf.side_effect = lambda *a, **kw: TemporaryFile(*a, **kw)

            # This is a relatively small add-on (1.2M) but we are using
            # a temporary file for all our linter output.
            result = json.loads(tasks.run_addons_linter(
                get_addon_file('typo-gecko.xpi')
            ))

            assert tmpf.call_count == 2
            assert result['success']
            assert result['warnings'] == 24
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


class TestWebextensionIncompatibilities(ValidatorTestCase):
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

    def test_webextension_upgrade_is_annotated(self):
        assert all(f.is_webextension is False
                   for f in self.addon.current_version.all_files)

        file_ = get_addon_file('valid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)

        upload.refresh_from_db()
        assert upload.processed_validation['is_upgrade_to_webextension']

        expected = ['validation', 'messages', 'webext_upgrade']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert upload.processed_validation['warnings'] == 1
        assert upload.valid

    def test_new_webextension_is_not_annotated(self):
        """https://github.com/mozilla/addons-server/issues/3679"""
        previous_file = self.addon.current_version.all_files[-1]
        previous_file.is_webextension = True
        previous_file.status = amo.STATUS_AWAITING_REVIEW
        previous_file.save()

        file_ = get_addon_file('valid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)

        upload.refresh_from_db()
        validation = upload.processed_validation

        assert 'is_upgrade_to_webextension' not in validation
        expected = ['validation', 'messages', 'webext_upgrade']
        assert not any(msg['id'] == expected for msg in validation['messages'])
        assert validation['warnings'] == 0
        assert upload.valid

    def test_webextension_webext_to_webext_not_annotated(self):
        previous_file = self.addon.current_version.all_files[-1]
        previous_file.is_webextension = True
        previous_file.save()

        file_ = get_addon_file('valid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        validation = upload.processed_validation

        assert 'is_upgrade_to_webextension' not in validation
        expected = ['validation', 'messages', 'webext_upgrade']
        assert not any(msg['id'] == expected for msg in validation['messages'])
        assert validation['warnings'] == 0
        assert upload.valid

    def test_webextension_no_webext_no_warning(self):
        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        validation = upload.processed_validation

        assert 'is_upgrade_to_webextension' not in validation
        expected = ['validation', 'messages', 'webext_upgrade']
        assert not any(msg['id'] == expected for msg in validation['messages'])

    def test_webextension_cannot_be_downgraded(self):
        self.update_files(is_webextension=True)

        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'webext_downgrade']
        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'

    def test_webextension_downgrade_only_warning_unlisted(self):
        self.update_files(is_webextension=True)
        self.make_addon_unlisted(self.addon)

        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')
        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=False)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'webext_downgrade']
        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'warning'
        assert validation['errors'] == 0

    def test_webextension_cannot_be_downgraded_ignore_deleted_version(self):
        """Make sure even deleting the previous version does not prevent
        the downgrade error."""
        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-2.1.106-fx.xpi')

        self.update_files(is_webextension=True)

        deleted_version = version_factory(
            addon=self.addon, file_kw={'is_webextension': False})
        deleted_version.delete()

        upload = FileUpload.objects.create(path=file_, addon=self.addon)

        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        expected = ['validation', 'messages', 'webext_downgrade']

        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'

    def test_no_upgrade_annotation_no_version(self):
        """Make sure there's no workaround the downgrade error."""
        self.addon.update(guid='guid@xpi')

        file_ = amo.tests.AMOPaths().file_fixture_path(
            'delicious_bookmarks-no-version.xpi')

        self.update_files(is_webextension=True)

        deleted_version = version_factory(
            addon=self.addon, file_kw={'is_webextension': False})
        deleted_version.delete()

        upload = FileUpload.objects.create(path=file_, addon=self.addon)
        upload.addon.version = None
        upload.addon.save()
        upload.save(update_fields=('version',))
        upload.refresh_from_db()

        tasks.validate(upload, listed=True)
        upload.refresh_from_db()

        expected = [u'testcases_installrdf', u'_test_rdf', u'missing_addon']

        validation = upload.processed_validation

        assert validation['messages'][0]['id'] == expected
        assert validation['messages'][0]['type'] == 'error'


class TestLegacyAddonRestrictions(ValidatorTestCase):
    def setUp(self):
        super(TestLegacyAddonRestrictions, self).setUp()

    def test_submit_legacy_addon_restricted(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        upload = FileUpload.objects.create(path=file_)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_restricted']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert not upload.valid

    def test_submit_legacy_extension_not_a_new_addon(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_legacy_extension_1st_version_in_that_channel(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        addon = addon_factory(
            version_kw={'version': '0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_restricted']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert not upload.valid

    def test_submit_legacy_extension_1st_version_in_that_channel_reverse(self):
        file_ = get_addon_file('valid_firefox_addon.xpi')
        addon = addon_factory(
            version_kw={'version': '0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=False)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        expected = ['validation', 'messages', 'legacy_addons_restricted']
        assert upload.processed_validation['messages'][0]['id'] == expected
        assert not upload.valid

    def test_submit_webextension(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_legacy_extension_targets_older_firefox_stricly(self):
        file_ = get_addon_file('valid_firefox_addon_strict_compatibility.xpi')
        upload = FileUpload.objects.create(path=file_)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_non_extension(self):
        file_ = get_addon_file('searchgeek-20090701.xml')
        upload = FileUpload.objects.create(path=file_)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_thunderbird_extension(self):
        file_ = get_addon_file('valid_firefox_and_thunderbird_addon.xpi')
        upload = FileUpload.objects.create(path=file_)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_restrict_firefox_53_alpha(self):
        data = {
            'messages': [],
            'errors': 0,
            'detected_type': 'extension',
            'metadata': {
                'is_webextension': False,
                'is_extension': True,
                'strict_compatibility': True,
                'applications': {
                    'firefox': {
                        'max': '53a1'
                    }
                }
            }
        }
        results = tasks.annotate_legacy_addon_restrictions(
            data, is_new_upload=True)
        assert results['errors'] == 1
        assert len(results['messages']) > 0
        assert results['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_restricted']

    def test_restrict_themes(self):
        data = {
            'messages': [],
            'errors': 0,
            'detected_type': 'theme',
            'metadata': {
                'is_extension': False,
                'strict_compatibility': False,
                'applications': {
                    'firefox': {
                        'max': '54.0'
                    }
                }
            }
        }
        results = tasks.annotate_legacy_addon_restrictions(
            data, is_new_upload=True)
        assert results['errors'] == 1
        assert len(results['messages']) > 0
        assert results['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_restricted']

    def test_submit_legacy_upgrade(self):
        # Works because it's not targeting >= 57.
        file_ = get_addon_file('valid_firefox_addon.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_legacy_upgrade_targeting_firefox_57(self):
        # Should error since it's a legacy extension targeting 57.
        file_ = get_addon_file('valid_firefox_addon_targeting_57.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        assert len(upload.processed_validation['messages']) == 1
        assert upload.processed_validation['messages'][0]['type'] == 'error'
        assert upload.processed_validation['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_max_version']
        assert not upload.valid

    def test_submit_legacy_upgrade_targeting_57_strict_compatibility(self):
        # Should error just like if it didn't have strict compatibility, that
        # does not matter: it's a legacy extension, it should not target 57.
        file_ = get_addon_file(
            'valid_firefox_addon_targeting_57_strict_compatibility.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 1
        assert len(upload.processed_validation['messages']) == 1
        assert upload.processed_validation['messages'][0]['type'] == 'error'
        assert upload.processed_validation['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_max_version']
        assert not upload.valid

    def test_submit_legacy_upgrade_targeting_star(self):
        # Should not error: extensions with a maxversion of '*' don't get the
        # error, the manifest parsing code will rewrite it as '56.*' instead.
        file_ = get_addon_file('valid_firefox_addon_targeting_star.xpi')
        addon = addon_factory(version_kw={'version': '0.1'})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_webextension_upgrade_targeting_firefox_57(self):
        # Should not error: it's targeting 57 but it's a webextension.
        file_ = get_addon_file('valid_webextension_targeting_57.xpi')
        addon = addon_factory(version_kw={'version': '0.1'},
                              file_kw={'is_webextension': True})
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        messages = upload.processed_validation['messages']
        assert len(messages) == 1
        assert messages[0]['message'] == ('&#34;strict_max_version&#34; '
                                          'not required.')
        assert upload.valid

    def test_submit_dictionary_upgrade_targeting_firefox_57(self):
        # Should not error: non-extensions types are not affected by the
        # restriction, even if they target 57.
        file_ = get_addon_file('dictionary_targeting_57.xpi')
        addon = addon_factory(version_kw={'version': '0.1'},
                              type=amo.ADDON_DICT)
        upload = FileUpload.objects.create(path=file_, addon=addon)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_submit_legacy_targeting_multiple_including_firefox_57(self):
        # By submitting a legacy extension targeting multiple apps, this add-on
        # avoids the restriction for new uploads, but it should still trigger
        # the one for legacy extensions targeting 57 or higher.
        data = {
            'messages': [],
            'errors': 0,
            'detected_type': 'extension',
            'metadata': {
                'is_webextension': False,
                'is_extension': True,
                'applications': {
                    'firefox': {
                        'max': '57.0'
                    },
                    'thunderbird': {
                        'max': '45.0'
                    }
                }
            }
        }
        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=True)
        assert results['errors'] == 1
        assert len(results['messages']) > 0
        assert results['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_max_version']

        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=False)
        assert results['errors'] == 1
        assert len(results['messages']) > 0
        assert results['messages'][0]['id'] == [
            'validation', 'messages', 'legacy_addons_max_version']

    def test_allow_upgrade_submission_targeting_firefox_and_thunderbird(self):
        # This should work regardless of whether the
        # disallow-thunderbird-and-seamonkey waffle is enabled, because it also
        # targets Firefox (it's a legacy one, but it targets Firefox < 57).
        data = {
            'messages': [],
            'errors': 0,
            'detected_type': 'extension',
            'metadata': {
                'is_webextension': False,
                'is_extension': True,
                'applications': {
                    'firefox': {
                        'max': '56.0'
                    },
                    'thunderbird': {
                        'max': '45.0'
                    }
                }
            }
        }
        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=False)
        assert results['errors'] == 0

        self.create_switch('disallow-thunderbird-and-seamonkey')
        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=False)
        assert results['errors'] == 0

    def test_disallow_thunderbird_seamonkey_waffle(self):
        # The disallow-thunderbird-and-seamonkey waffle is not enabled so it
        # should still work, even though it's only targeting Thunderbird.
        data = {
            'messages': [],
            'errors': 0,
            'detected_type': 'extension',
            'metadata': {
                'is_webextension': False,
                'is_extension': True,
                'applications': {
                    'thunderbird': {
                        'max': '45.0'
                    }
                }
            }
        }
        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=True)
        assert results['errors'] == 0

        # With the waffle enabled however, it should be blocked.
        self.create_switch('disallow-thunderbird-and-seamonkey')
        results = tasks.annotate_legacy_addon_restrictions(
            data.copy(), is_new_upload=True)
        assert results['errors'] == 1
        assert len(results['messages']) > 0
        assert results['messages'][0]['id'] == [
            'validation', 'messages', 'thunderbird_and_seamonkey_migration']


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
            automated_signing=False)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations(self):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk, amo.RELEASE_CHANNEL_LISTED)
        self.create_version_for_upload.assert_called_with(
            self.addon, upload, amo.RELEASE_CHANNEL_LISTED)

    @mock.patch('olympia.devhub.tasks.FileUpload.passed_all_validations',
                False)
    def test_file_not_passed_all_validations(self):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk, amo.RELEASE_CHANNEL_LISTED)
        assert not self.create_version_for_upload.called


class TestCreateVersionForUpload(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCreateVersionForUpload, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.create_version_for_upload = (
            tasks.create_version_for_upload.non_atomic)
        self.mocks = {}
        for key in ['Version.from_upload', 'parse_addon']:
            patcher = mock.patch('olympia.devhub.tasks.%s' % key)
            self.mocks[key] = patcher.start()
            self.addCleanup(patcher.stop)
        self.user = user_factory()

    def create_upload(self, version='1.0'):
        return FileUpload.objects.create(
            addon=self.addon, version=version, user=self.user,
            validation='{"errors":0}', automated_signing=False)

    def test_file_passed_all_validations_not_most_recent(self):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # Check that the older file won't turn into a Version.
        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

        # But the newer one will.
        self.create_version_for_upload(self.addon, newer_upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        self.mocks['Version.from_upload'].assert_called_with(
            newer_upload, self.addon, [amo.PLATFORM_ALL.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_version_exists(self):
        upload = self.create_upload()
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent_failed(self):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1),
                            valid=False,
                            validation=json.dumps({"errors": 5}))

        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent(self):
        upload = self.create_upload(version='1.0')
        newer_upload = self.create_upload(version='0.5')
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # The Version is created because the newer upload is for a different
        # version_string.
        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_beta_string(self):
        upload = self.create_upload(version='1.0-beta1')
        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)

    def test_file_passed_all_validations_no_version(self):
        upload = self.create_upload(version=None)
        self.create_version_for_upload(self.addon, upload,
                                       amo.RELEASE_CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(
            upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.mocks['parse_addon'].return_value)


class TestAPIKeyInSubmission(TestCase):

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
        upload = FileUpload.objects.create(path=self.file, user=self.user)
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
        upload = FileUpload.objects.create(path=self.file, addon=self.addon,
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
        upload = FileUpload.objects.create(path=self.file, addon=self.addon,
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
            upload = FileUpload.objects.create(path=self.file, user=self.user)
            tasks.validate(upload, listed=True)
            upload.refresh_from_db()
            mock_revoke.apply_async.assert_called_with(
                kwargs={'key_id': self.key.id}, countdown=120)

        assert not upload.valid

    def test_does_not_revoke_for_different_author(self):
        different_author = user_factory()
        upload = FileUpload.objects.create(path=self.file,
                                           user=different_author)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.valid

    def test_does_not_revoke_safe_webextension(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_, user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_binary_content(self):
        file_ = get_addon_file('webextension_containing_binary_files.xpi')
        upload = FileUpload.objects.create(path=file_, user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        assert upload.processed_validation['errors'] == 0
        assert upload.processed_validation['messages'] == []
        assert upload.valid

    def test_validation_finishes_if_containing_invalid_filename(self):
        file_ = get_addon_file('invalid_webextension.xpi')
        upload = FileUpload.objects.create(path=file_, user=self.user)
        tasks.validate(upload, listed=True)

        upload.refresh_from_db()

        # https://github.com/mozilla/addons-server/issues/8208
        # causes this to be 2 (and invalid) instead of 0 (and valid).
        # The invalid filename error is caught and raised outside of this
        # validation task.
        assert upload.processed_validation['errors'] == 2
        assert not upload.valid
