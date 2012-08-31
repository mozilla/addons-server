import os
import path
import shutil
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
from nose.tools import eq_
from PIL import Image

import amo
import amo.tests
from addons.models import Addon
from amo.tests.test_helpers import get_image_path
from devhub import tasks
from files.models import FileUpload


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
        for rsize, fsize in zip(resize_size, final_size):
            dest_name = str(path.path(settings.ADDON_ICONS_PATH) / '1234')

            tasks.resize_icon(src.name, dest_name, resize_size, locally=True)
            dest_image = Image.open(open('%s-%s.png' % (dest_name, rsize)))
            eq_(dest_image.size, fsize)

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
    else:
        dest = tempfile.mktemp(suffix='.png')
        tasks.resize_icon(src.name, dest, resize_size, locally=True)
        dest_image = Image.open(dest)
        eq_(dest_image.size, final_size)

    assert not os.path.exists(src.name)


class TestValidator(amo.tests.TestCase):

    def setUp(self):
        self.upload = FileUpload.objects.create()
        assert not self.upload.valid

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    @mock.patch('devhub.tasks.run_validator')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        tasks.validator(self.upload.pk)
        assert self.get_upload().valid

    @mock.patch('devhub.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        tasks.validator(self.upload.pk)
        assert not self.get_upload().valid

    @mock.patch('devhub.tasks.run_validator')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        eq_(self.upload.task_error, None)
        with self.assertRaises(Exception):
            tasks.validator(self.upload.pk)
        error = self.get_upload().task_error
        assert error.startswith('Traceback (most recent call last)'), error


class TestFlagBinary(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
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
