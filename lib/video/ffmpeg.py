import logging
import re
import tempfile

from django.conf import settings

from django_statsd.clients import statsd
from tower import ugettext as _

from .utils import check_output, subprocess, VideoBase


log = logging.getLogger('z.video')

formats_re = [
    re.compile('Input #0, ([\w,]+)?, from'),
    re.compile('doctype\s+: (\w+)'),
]
duration_re = re.compile('Duration: (\d{2}):(\d{2}):(\d{2}.\d{2}),')
dimensions_re = re.compile('Stream #0.*?(\d+)x(\d+)')
version_re = re.compile('ffmpeg version (\d\.+)', re.I)


class Video(VideoBase):
    name = settings.FFMPEG_BINARY

    def _call(self, note, catch_error, *args):
        with statsd.timer('video.ffmpeg.%s' % note):
            args = [self.name,
                    '-y',  # Don't prompt for overwrite of file
                    '-i', self.filename] + list(args)
            log.info('ffmpeg called with: %s' % ' '.join(args))
            try:
                res = check_output(args, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError, e:
                # This is because to get the information about a file
                # you specify the input file, but not the output file
                # ffmpeg errors, but returns all the information we want.
                if not catch_error:
                    log.error('ffmpeg failed with: %s' % e.output)
                    raise
                else:
                    res = e.output
        return res

    def get_meta(self):
        """
        Get the metadata for the file. You should call this first
        so we can populate some meta data and ensure that the file is valid.
        """
        result = self._call('meta', True)
        data = {}
        for fmt in formats_re:
            formats = fmt.search(result)
            if formats:
                data['formats'] = formats.group(1).split(',')

        duration = duration_re.search(result)
        if duration:
            data['duration'] = ((3600 * int(duration.group(1)))
                                + (60 * int(duration.group(2)))
                                + float(duration.group(3)))
        dimensions = dimensions_re.search(result)
        if dimensions:
            data['dimensions'] = (int(dimensions.group(1)),
                                  int(dimensions.group(2)))
        self.meta = data

    def get_screenshot(self, size):
        """
        Gets a screenshot half way through the video. Will return the location
        of the temporary file. It is up to the calling function to remove the
        temporary file after its completed.

        `size`: a tuple of the width and height
        """
        assert self.is_valid()
        assert self.meta.get('duration')
        halfway = int(self.meta['duration'] / 2)
        dest = tempfile.mkstemp(suffix='.png')[1]
        self._call('screenshot',
                   False,
                   '-vframes', '1',  # Only grab one frame.
                   '-ss', str(halfway),  # Start half way through.
                   '-s', '%sx%s' % size,  # Size of image.
                   dest)
        return dest

    def get_encoded(self, size):
        """
        Recodes the video into a different size and sets its bit rate
        to something suitable. In theory we are also doing this to ensure
        that the video is cleaned. Maybe.

        Will return the location of the temporary file. It is up to the
        calling function to remove the temporary file after its completed.

        `size`: a tuple of the width and height
        """
        assert self.is_valid()
        dest = tempfile.mkstemp(suffix='.webm')[1]
        self._call('encode',
                   False,
                   '-s', '%sx%s' % size,  # Size of video.
                   dest)
        return dest

    def is_valid(self):
        assert self.meta is not None
        self.errors = []
        if 'webm' not in self.meta.get('formats', ''):
            self.errors.append(_('Videos must be in WebM.'))

        # TODO(andym): More checks on duration, file size, bit rate?
        return not self.errors

    @classmethod
    def library_available(cls):
        try:
            output = check_output([cls.name, '-version'],
                                  stderr=subprocess.STDOUT)
            # If in the future we want to check for an ffmpeg version
            # this is the place to do it.
            return bool(version_re.match(output))
        except (OSError, subprocess.CalledProcessError):
            pass
