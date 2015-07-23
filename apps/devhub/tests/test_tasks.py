import json
import os
import shutil
import tempfile

from django.conf import settings
from django.test.utils import override_settings

import mock
import pytest
from nose.tools import eq_
from PIL import Image

import amo
import amo.tests
from addons.models import Addon
from amo.helpers import user_media_path
from amo.tests.test_helpers import get_image_path
from devhub import tasks
from files.models import FileUpload


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

    @mock.patch('devhub.tasks.run_validator')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        eq_(self.upload.task_error, None)
        with self.assertRaises(Exception):
            tasks.validate(self.upload)
        error = self.get_upload().task_error
        assert error.startswith('Traceback (most recent call last)'), error

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
        eq_(self.upload.task_error, None)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert validation['passed_auto_validation']

        result['signing_summary']['low'] = 1
        _mock.return_value = json.dumps(result)
        eq_(self.upload.task_error, None)
        tasks.validate(self.upload)
        validation = json.loads(self.get_upload().validation)
        assert not validation['passed_auto_validation']

    @mock.patch('devhub.tasks.run_validator')
    def test_annotate_passed_auto_validation_bogus_result(self, _mock):
        """Don't set passed_auto_validation, don't fail if results is bogus."""
        _mock.return_value = '{"errors": 0}'
        eq_(self.upload.task_error, None)
        tasks.validate(self.upload)
        assert (json.loads(self.get_upload().validation) ==
                {"passed_auto_validation": True, "errors": 0,
                 "signing_summary": {"high": 0, "medium": 0,
                                     "low": 0, "trivial": 0}})


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
