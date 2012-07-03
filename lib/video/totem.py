import logging
import os
import re
import tempfile

from django.conf import settings

from django_statsd.clients import statsd
from tower import ugettext as _

from .utils import check_output, subprocess, VideoBase


log = logging.getLogger('z.video')

format_re = re.compile('TOTEM_INFO_VIDEO_CODEC=([\w]+)')
duration_re = re.compile('TOTEM_INFO_DURATION=(\d+)')


class Video(VideoBase):
    name = settings.TOTEM_BINARIES

    def _call_indexer(self):
        with statsd.timer('video.totem.meta'):
            args = [self.name['indexer'],
                    self.filename]
            if not os.path.exists(self.filename):
                log.info('file did not exist for thumbnailing: %s'
                         % self.filename)
                raise
            log.info('totem called with: %s' % ' '.join(args))
            try:
                res = check_output(args, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError, e:
                log.error('totem failed with: %s' % e.output)
                raise
            log.info('totem returned: %s' % res)
        return res

    def _call_thumbnailer(self, timepoint, destination, size):
        with statsd.timer('video.totem.screenshot'):
            args = [self.name['thumbnailer'],
                    '-t', timepoint,  # Start at this point.
                    '-s', size,  # This can only be one of the sizes.
                    '-r',  # Remove overlayed borders.
                    self.filename,
                    destination]
            log.info('totem called with: %s' % ' '.join(args))
            try:
                res = check_output(args, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError, e:
                log.error('totem failed with: %s' % e.output)
                raise
        return res

    def get_meta(self):
        result = self._call_indexer()
        data = {}
        formats = format_re.search(result)
        if formats:
            data['formats'] = formats.group(1)

        duration = duration_re.search(result)
        if duration:
            data['duration'] = duration.group(1)

        self.meta = data

    def get_screenshot(self, size):
        assert self.is_valid()
        assert self.meta.get('duration')
        halfway = int(self.meta['duration']) / 2
        dest = tempfile.mkstemp(suffix='.png')[1]
        self._call_thumbnailer(str(halfway), dest, str(max(size)))
        return dest

    def is_valid(self):
        assert self.meta is not None
        self.errors = []
        if 'VP8' not in self.meta.get('formats', ''):
            self.errors.append(_('Videos must be in WebM.'))

        #TODO(andym): More checks on duration, file size, bit rate?
        return not self.errors

    @classmethod
    def library_available(cls):
        try:
            # We'll assume if the thumbnailer is there so is the indexer.
            check_output([cls.name['thumbnailer'], '-help'],
                         stderr=subprocess.STDOUT)
            return True
        except (OSError, subprocess.CalledProcessError):
            pass
