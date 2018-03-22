import os
import StringIO
import subprocess
import tempfile
from base64 import b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage

from PIL import Image

import olympia.core.logger
from olympia import amo


log = olympia.core.logger.getLogger('z.versions.utils')


def write_svg_to_png(svg_content, out):
    tmp_args = {'dir': settings.TMP_PATH, 'mode': 'wb', 'suffix': '.svg'}
    with tempfile.NamedTemporaryFile(**tmp_args) as temporary_svg:
        temporary_svg.write(svg_content)
        temporary_svg.flush()

        size = None
        try:
            if not os.path.exists(os.path.dirname(out)):
                os.makedirs(out)
            command = [
                settings.RSVG_CONVERT_BIN,
                '-o', out,
                temporary_svg.name
            ]
            subprocess.check_call(command)
            size = amo.THEME_PREVIEW_SIZE
        except IOError as io_error:
            log.debug(io_error)
        except subprocess.CalledProcessError as process_error:
            log.debug(process_error)
    return size


def encode_header_image(path):
    try:
        with storage.open(path, 'rb') as image:
            header_blob = image.read()
            with Image.open(StringIO.StringIO(header_blob)) as header_image:
                (width, height) = header_image.size
            src = 'data:image/%s;base64,%s' % (
                header_image.format.lower(), b64encode(header_blob))
    except IOError as io_error:
        log.debug(io_error)
        return (None, 0, 0)
    return (src, width, height)


class AdditionalBackground(object):

    @classmethod
    def split_alignment(cls, alignment):
        alignments = alignment.split()
        # e.g. "center top"
        if len(alignments) >= 2:
            return (alignments[0], alignments[1])
        elif len(alignments) == 1:
            # e.g. "left", which is the same as 'left center'
            if alignments[0] in ['left', 'right']:
                return (alignments[0], 'center')
            # e.g. "top", which is the same as 'center top'
            else:
                return ('center', alignments[0])
        else:
            return ('', '')

    def __init__(self, path, alignment, tiling, header_root):
        # If there an unequal number of alignments or tiling to srcs the value
        # will be None so use defaults.
        alignment = (alignment or 'left top').lower()
        tiling = (tiling or 'no-repeat').lower()
        self.src, self.width, self.height = encode_header_image(
            os.path.join(header_root, path))
        self.pattern_width = (self.width if tiling in ['repeat', 'repeat-x']
                              else '100%')
        self.pattern_height = (self.height if tiling in ['repeat', 'repeat-y']
                               else '100%')
        align_x, align_y = self.split_alignment(alignment)
        if align_x == 'right':
            self.pattern_x = amo.THEME_PREVIEW_SIZE.width - self.width
        elif align_x == 'center':
            self.pattern_x = (amo.THEME_PREVIEW_SIZE.width - self.width) / 2
        else:
            self.pattern_x = 0
        if align_y == 'bottom':
            self.pattern_y = amo.THEME_PREVIEW_SIZE.height - self.height
        elif align_y == 'center':
            self.pattern_y = (amo.THEME_PREVIEW_SIZE.height - self.height) / 2
        else:
            self.pattern_y = 0
