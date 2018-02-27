import mock
import os
import tempfile

from django.conf import settings

from olympia.addons.tasks import (
    create_persona_preview_images, save_persona_image)
from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size


class TestPersonaImageFunctions(TestCase):
    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_create_persona_preview_image(self, pngcrush_image_mock):
        addon = addon_factory()
        addon.modified = self.days_ago(41)
        # Given an image, a 680x100 and a 32x32 thumbnails need to be generated
        # and processed with pngcrush.
        expected_dst1 = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        expected_dst2 = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        create_persona_preview_images(
            src=get_image_path('persona-header.jpg'),
            full_dst=[expected_dst1.name, expected_dst2.name],
            set_modified_on=[addon],
        )
        # pngcrush_image should have been called twice, once for each
        # destination thumbnail.
        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            expected_dst1.name)
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            expected_dst2.name)

        assert image_size(expected_dst1.name) == (680, 100)
        assert image_size(expected_dst2.name) == (32, 32)

        addon.reload()
        self.assertCloseToNow(addon.modified)

    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_save_persona_image(self, pngcrush_image_mock):
        # save_persona_image() simply saves an image as a png to the
        # destination file. The image should be processed with pngcrush.
        expected_dst = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        save_persona_image(
            get_image_path('persona-header.jpg'),
            expected_dst.name
        )
        # pngcrush_image should have been called once.
        assert pngcrush_image_mock.call_count == 1
        assert pngcrush_image_mock.call_args_list[0][0][0] == expected_dst.name

    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_save_persona_image_not_an_image(self, pngcrush_image_mock):
        # If the source is not an image, save_persona_image() should just
        # return early without writing the destination or calling pngcrush.
        expected_dst = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        save_persona_image(
            get_image_path('non-image.png'),
            expected_dst.name
        )
        # pngcrush_image should not have been called.
        assert pngcrush_image_mock.call_count == 0
        # the destination file should not have been written to.
        assert os.stat(expected_dst.name).st_size == 0
