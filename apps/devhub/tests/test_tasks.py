import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

from django.conf import settings
from django.test.utils import override_settings

import mock
import pytest
from nose.tools import eq_
from PIL import Image

import amo
import amo.tests
from constants.base import VALIDATOR_SKELETON_RESULTS
from addons.models import Addon
from amo.helpers import user_media_path
from amo.tests.test_helpers import get_image_path
from devhub import tasks
from files.models import FileUpload
from versions.models import Version


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

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)

    # resize_icon removes the original
    shutil.copyfile(img, src.name)

    src_image = Image.open(src.name)
    eq_(src_image.size, original_size)

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
            eq_(dest_image.size, fsize)

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
        shutil.rmtree(uploadto)
    else:
        dest = tempfile.mktemp(suffix='.png')
        tasks.resize_icon(src.name, dest, resize_size, locally=True)
        dest_image = Image.open(dest)
        eq_(dest_image.size, final_size)

    assert not os.path.exists(src.name)


class TestValidator(amo.tests.TestCase):
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
        self.upload = FileUpload.objects.create()
        assert not self.upload.valid

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    @mock.patch('devhub.tasks.run_validator')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        assert self.get_upload().valid

    @mock.patch('devhub.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        tasks.validate(self.upload)
        assert not self.get_upload().valid

    @mock.patch('validator.submain.test_package')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception

        self.upload.update(
            path=os.path.join(settings.ROOT,
                              'apps/devhub/tests/addons/desktop.xpi'))

        assert self.upload.validation is None

        tasks.validate(self.upload)
        self.upload.reload()
        validation = self.upload.processed_validation
        assert validation
        assert validation['errors'] == 1
        assert validation['messages'][0]['id'] == ['validator',
                                                   'unexpected_exception']
        assert not self.upload.valid

    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=False)
    @mock.patch('devhub.tasks.annotate_validation_results')
    @mock.patch('devhub.tasks.run_validator')
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
    @mock.patch('devhub.tasks.run_validator')
    def test_validation_signing_warning(self, _mock):
        """If we sign addons, warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['warnings'] == 1
        assert len(validation['messages']) == 1

    @override_settings(SIGNING_SERVER='', PRELIMINARY_SIGNING_SERVER='')
    @mock.patch('devhub.tasks.run_validator')
    def test_validation_no_signing_warning(self, _mock):
        """If we're not signing addon don't warn on signed addon submission."""
        _mock.return_value = self.mock_sign_addon_warning
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['warnings'] == 0
        assert len(validation['messages']) == 0

    @mock.patch('devhub.tasks.run_validator')
    def test_annotate_passed_auto_validation(self, _mock):
        """Set passed_auto_validation on reception of the results."""
        result = {'signing_summary': {'trivial': 1, 'low': 0, 'medium': 0,
                                      'high': 0},
                  'errors': 0}

        _mock.return_value = json.dumps(result)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['passed_auto_validation']

    @mock.patch('devhub.tasks.run_validator')
    def test_annotate_failed_auto_validation(self, _mock):
        """Set passed_auto_validation on reception of the results."""
        result = {'signing_summary': {'trivial': 0, 'low': 1, 'medium': 0,
                                      'high': 0},
                  'errors': 0}

        _mock.return_value = json.dumps(result)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert not validation['passed_auto_validation']

    @mock.patch('devhub.tasks.run_validator')
    def test_annotate_passed_auto_validation_bogus_result(self, _mock):
        """Don't set passed_auto_validation, don't fail if results is bogus."""
        _mock.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        assert (json.loads(self.get_upload().validation) ==
                {"passed_auto_validation": True, "errors": 0,
                 "signing_summary": {"high": 0, "medium": 0,
                                     "low": 0, "trivial": 0}})

    @mock.patch('validator.validate.validate')
    @mock.patch('devhub.tasks.track_validation_stats')
    def test_track_validation_stats(self, mock_track, mock_validate):
        mock_validate.return_value = '{"errors": 0}'
        tasks.validate(self.upload)
        mock_track.assert_called_with(mock_validate.return_value)


class TestTrackValidatorStats(amo.tests.TestCase):

    def setUp(self):
        super(TestTrackValidatorStats, self).setUp()
        patch = mock.patch('devhub.tasks.statsd.incr')
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


class TestFlagBinary(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestFlagBinary, self).setUp()
        self.addon = Addon.objects.get(pk=3615)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_binary(self, _mock):
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 1, '
                              '"contains_binary_content": 0}}')
        tasks.flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, True)
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 0, '
                              '"contains_binary_content": 1}}')
        tasks.flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, True)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_not_binary(self, _mock):
        _mock.return_value = ('{"metadata":{"contains_binary_extension": 0, '
                              '"contains_binary_content": 0}}')
        tasks.flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, False)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_error(self, _mock):
        _mock.side_effect = RuntimeError()
        tasks.flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, False)


@mock.patch('devhub.tasks.send_html_mail_jinja')
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


class TestSubmitFile(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestSubmitFile, self).setUp()
        self.addon = Addon.objects.get(pk=3615)

    def create_upload(self, version='1.0'):
        return FileUpload.objects.create(
            addon=self.addon, version=version, validation='{"errors":0}',
            automated_signing=self.addon.automated_signing)

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations(self, create_version):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk)
        create_version.assert_called_with(upload, self.addon,
                                          [amo.PLATFORM_ALL.id])

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', False)
    def test_file_not_passed_all_validations(self, create_version):
        upload = self.create_upload()
        tasks.submit_file(self.addon.pk, upload.pk)
        assert not create_version.called

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations_not_most_recent(self, create_version):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # Check that the older file won't turn into a Version.
        tasks.submit_file(self.addon.pk, upload.pk)
        assert not create_version.called

        # But the newer one will.
        tasks.submit_file(self.addon.pk, newer_upload.pk)
        create_version.assert_called_with(
            newer_upload, self.addon, [amo.PLATFORM_ALL.id])

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations_version_exists(self, create_version):
        upload = self.create_upload()
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        tasks.submit_file(self.addon.pk, upload.pk)
        assert not create_version.called

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations_most_recent_failed(self,
                                                            create_version):
        upload = self.create_upload()
        newer_upload = self.create_upload()
        newer_upload.update(created=datetime.today() + timedelta(hours=1),
                            valid=False,
                            validation=json.dumps({"errors": 5}))

        tasks.submit_file(self.addon.pk, upload.pk)
        assert not create_version.called

    @mock.patch('devhub.tasks.Version.from_upload')
    @mock.patch('apps.devhub.tasks.FileUpload.passed_all_validations', True)
    def test_file_passed_all_validations_most_recent(self, create_version):
        upload = self.create_upload(version='1.0')
        newer_upload = self.create_upload(version='0.5')
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # The Version is created because the newer upload is for a different
        # version_string.
        tasks.submit_file(self.addon.pk, upload.pk)
        create_version.assert_called_with(
            upload, self.addon, [amo.PLATFORM_ALL.id])
