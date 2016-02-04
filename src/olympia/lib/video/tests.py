import os
import stat
import tempfile

import pytest
from mock import Mock, patch
from nose import SkipTest
from nose.tools import eq_

from django.conf import settings

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.devhub.models import UserLog
from olympia.lib.video import get_library
from olympia.lib.video import ffmpeg, totem
from olympia.lib.video.tasks import resize_video
from olympia.users.models import UserProfile


pytestmark = pytest.mark.django_db

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

totem_indexer_good = """
TOTEM_INFO_DURATION=10
TOTEM_INFO_HAS_VIDEO=True
TOTEM_INFO_VIDEO_WIDTH=640
TOTEM_INFO_VIDEO_HEIGHT=360
TOTEM_INFO_VIDEO_CODEC=VP8 video
TOTEM_INFO_FPS=25
TOTEM_INFO_HAS_AUDIO=True
TOTEM_INFO_AUDIO_BITRATE=128
TOTEM_INFO_AUDIO_CODEC=Vorbis
TOTEM_INFO_AUDIO_SAMPLE_RATE=44100
TOTEM_INFO_AUDIO_CHANNELS=Stereo
"""

totem_indexer_bad = """
TOTEM_INFO_HAS_VIDEO=False
TOTEM_INFO_HAS_AUDIO=False
"""


class TestFFmpegVideo(TestCase):

    def setUp(self):
        super(TestFFmpegVideo, self).setUp()
        self.video = ffmpeg.Video(files['good'])
        if not ffmpeg.Video.library_available():
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


class TestBadFFmpegVideo(TestCase):

    def setUp(self):
        super(TestBadFFmpegVideo, self).setUp()
        self.video = ffmpeg.Video(files['bad'])
        if not self.video.library_available():
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


class TestTotemVideo(TestCase):

    def setUp(self):
        super(TestTotemVideo, self).setUp()
        self.video = totem.Video(files['good'])
        self.video._call_indexer = Mock()

    def test_meta(self):
        self.video._call_indexer.return_value = totem_indexer_good
        self.video.get_meta()
        eq_(self.video.meta['formats'], 'VP8')
        eq_(self.video.meta['duration'], '10')

    def test_valid(self):
        self.video._call_indexer = Mock()
        self.video._call_indexer.return_value = totem_indexer_good
        self.video.get_meta()
        assert self.video.is_valid()

    def test_not_valid(self):
        self.video._call_indexer.return_value = totem_indexer_bad
        self.video.get_meta()
        assert not self.video.is_valid()

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


@patch('olympia.lib.video.totem.Video.library_available')
@patch('olympia.lib.video.ffmpeg.Video.library_available')
@patch.object(settings, 'VIDEO_LIBRARIES',
              ['olympia.lib.video.totem', 'olympia.lib.video.ffmpeg'])
def test_choose(ffmpeg_, totem_):
    ffmpeg_.return_value = True
    totem_.return_value = True
    eq_(get_library(), totem.Video)
    totem_.return_value = False
    eq_(get_library(), ffmpeg.Video)
    ffmpeg_.return_value = False
    eq_(get_library(), None)


class TestTask(TestCase):
    # TODO(andym): make these more sparkly and cope with totem and not blow
    # up all the time.

    def setUp(self):
        super(TestTask, self).setUp()
        self.mock = Mock()
        self.mock.thumbnail_path = tempfile.mkstemp()[1]
        self.mock.image_path = tempfile.mkstemp()[1]
        self.mock.pk = 1

    @patch('olympia.lib.video.tasks._resize_video')
    def test_resize_error(self, _resize_video):
        user = UserProfile.objects.create(email='a@a.com')
        _resize_video.side_effect = ValueError
        with self.assertRaises(ValueError):
            resize_video(files['good'], self.mock, user=user)
        assert self.mock.delete.called
        assert UserLog.objects.filter(
            user=user, activity_log__action=amo.LOG.VIDEO_ERROR.id).exists()

    @patch('olympia.lib.video.tasks._resize_video')
    def test_resize_failed(self, _resize_video):
        user = UserProfile.objects.create(email='a@a.com')
        _resize_video.return_value = None
        resize_video(files['good'], self.mock, user=user)
        assert self.mock.delete.called

    def test_resize_video(self):
        raise SkipTest
        resize_video(files['good'], self.mock)
        assert isinstance(self.mock.sizes, dict)
        assert self.mock.save.called

    def test_resize_image(self):
        raise SkipTest
        resize_video(files['bad'], self.mock)
        assert not isinstance(self.mock.sizes, dict)
        assert not self.mock.save.called
