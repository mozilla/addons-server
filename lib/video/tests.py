import os
import stat
import tempfile

from mock import Mock, patch

from nose import SkipTest
from nose.tools import eq_

import waffle

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

older_output = """
Input #0, matroska,webm, from 'lib/video/fixtures/disco-truncated.webm':
  Duration: 00:00:10.00, start: 0.000000, bitrate: 298 kb/s
    Stream #0:0(eng): Video: vp8, yuv420p, 640x360, SAR 1:1 DAR 16:9,
    Stream #0:1(eng): Audio: vorbis, 44100 Hz, stereo, s16 (default)
"""

other_output = """
Input #0, matroska, from 'disco-truncated.webm':
  Metadata:
    doctype         : webm
"""


class TestGoodVideo(amo.tests.TestCase):

    def setUp(self):
        self.video = ffmpeg.Video(files['good'])
        if not self.video.encoder_available():
            raise SkipTest
        self.video._call = Mock()
        self.video._call.return_value = older_output

    def test_meta(self):
        self.video.get_meta()
        eq_(self.video.meta['formats'], ['matroska', 'webm'])
        eq_(self.video.meta['duration'], 10.0)
        eq_(self.video.meta['dimensions'], (640, 360))

    def test_valid(self):
        self.video.get_meta()
        assert self.video.is_valid()

    def test_dev_valid(self):
        self.video._call.return_value = other_output
        self.video.get_meta()
        eq_(self.video.meta['formats'], ['webm'])

    # These tests can be a little bit slow, to say the least so they are
    # skipped. Un-skip them if you want.
    def test_screenshot(self):
        raise SkipTest
        self.video.get_meta()
        try:
            screenshot = self.video.get_screenshot(amo.ADDON_PREVIEW_SIZES[0])
            assert os.stat(screenshot)[stat.ST_SIZE]
        finally:
            os.remove(screenshot)

    def test_encoded(self):
        raise SkipTest
        self.video.get_meta()
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
        waffle.models.Switch.objects.create(name='video-encode', active=True)
        self.mock = Mock()
        self.mock.thumbnail_path = tempfile.mkstemp()[1]
        self.mock.image_path = tempfile.mkstemp()[1]
        self.mock.pk = 1
        if not ffmpeg.Video('').encoder_available():
            raise SkipTest

    @patch('lib.video.ffmpeg.Video.get_encoded')
    def test_resize_video_no_encode(self, get_encoded):
        raise SkipTest
        waffle.models.Switch.objects.update(name='video-encode', active=False)
        resize_video(files['good'], self.mock)
        assert not get_encoded.called
        assert isinstance(self.mock.sizes, dict)
        assert self.mock.save.called

    def test_resize_video(self):
        raise SkipTest
        resize_video(files['good'], self.mock)
        assert isinstance(self.mock.sizes, dict)
        assert self.mock.save.called

    def test_resize_image(self):
        resize_video(files['bad'], self.mock)
        assert not isinstance(self.mock.sizes, dict)
        assert not self.mock.save.called
