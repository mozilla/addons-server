import os
import stat
import tempfile

from mock import Mock

from nose import SkipTest
from nose.tools import eq_

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from lib.video import ffmpeg
from lib.video.tasks import resize_video


files = {
    'good': os.path.join(os.path.dirname(__file__),
                         'fixtures/disco-truncated.webm'),
    'bad': get_image_path('mozilla.png'),
}


class TestGoodVideo(amo.tests.TestCase):

    def setUp(self):
        self.video = ffmpeg.Video(files['good'])
        if not self.video.encoder_available():
            raise SkipTest
        self.video.get_meta()

    def test_meta(self):
        eq_(self.video.meta['formats'], ['matroska', 'webm'])
        eq_(self.video.meta['duration'], 10.0)
        eq_(self.video.meta['dimensions'], (640, 360))

    def test_valid(self):
        assert self.video.is_valid()

    # These tests can be a little bit slow, to say the least so they are
    # skipped. Un-skip them if you want.
    def test_screenshot(self):
        #raise SkipTest
        try:
            screenshot = self.video.get_screenshot(amo.ADDON_PREVIEW_SIZES[0])
            assert os.stat(screenshot)[stat.ST_SIZE]
        finally:
            os.remove(screenshot)

    def test_encoded(self):
        #raise SkipTest
        try:
            video = self.video.get_encoded(amo.ADDON_PREVIEW_SIZES[0])
            assert os.stat(video)[stat.ST_SIZE]
        finally:
            os.remove(video)


class TestBadVideo(amo.tests.TestCase):

    def setUp(self):
        self.video = ffmpeg.Video(files['bad'])
        if not self.video.encoder_available():
            raise SkipTest
        self.video.get_meta()

    def test_meta(self):
        eq_(self.video.meta['formats'], ['image2'])
        assert not self.video.is_valid()

    def test_valid(self):
        assert not self.video.is_valid()

    def test_screenshot(self):
        self.assertRaises(AssertionError, self.video.get_screenshot,
                          amo.ADDON_PREVIEW_SIZES[0])

    def test_encoded(self):
        self.assertRaises(AssertionError, self.video.get_encoded,
                          amo.ADDON_PREVIEW_SIZES[0])


class TestTask(amo.tests.TestCase):

    def setUp(self):
        self.mock = Mock()
        self.mock.thumbnail_path = tempfile.mkstemp()[1]
        self.mock.image_path = tempfile.mkstemp()[1]
        self.mock.pk = 1

    def test_resize_video(self):
        resize_video(files['good'], self.mock)
        assert isinstance(self.mock.sizes, dict)
        assert self.mock.save.called

    def test_resize_image(self):
        resize_video(files['bad'], self.mock)
        assert not isinstance(self.mock.sizes, dict)
        assert not self.mock.save.called
