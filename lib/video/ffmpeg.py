import logging
import re
import subprocess
import tempfile

from django.conf import settings

from django_statsd.clients import statsd


log = logging.getLogger('z.video')

formats_re = re.compile('Input #0, ([\w,]+)?, from')
duration_re = re.compile('Duration: (\d{2}):(\d{2}):(\d{2}.\d{2}),')
dimensions_re = re.compile('Stream #0.*?(\d+)x(\d+)')
version_re = re.compile('ffmpeg version (\d\.+)')


def check_output(*popenargs, **kwargs):
    # Tell thee, check_output was from Python 2.7 untimely ripp'd.
    # check_output shall never vanquish'd be until
    # Marketplace moves to Python 2.7.
    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
    output, unused_err = process.communicate()
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        raise subprocess.CalledProcessError(retcode, cmd, output=output)
    return output


class Video(object):

    def __init__(self, filename):
        self.name = settings.FFMPEG_BINARY
        self.filename = filename
        self.meta = None
        self.errors = []

    def _call(self, note, catch_error, *args):
        with statsd.timer('video.%s' % note):
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
        formats = formats_re.search(result)
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
            self.errors.append('Must be a valid webm video')

        #TODO(andym): More checks on duration, file size, bit rate?
        return not self.errors

    def encoder_available(self):
        try:
            output = check_output([self.name, '-version'],
                                  stderr=subprocess.STDOUT)
            # If in the future we want to check for an ffmpeg version
            # this is the place to do it.
            return bool(version_re.match(output))
        except (OSError, subprocess.CalledProcessError):
            pass
