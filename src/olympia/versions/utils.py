import os
import StringIO
import subprocess
import tempfile
from base64 import b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage

from PIL import Image

import olympia.core.logger


log = olympia.core.logger.getLogger('z.versions.utils')


def write_svg_to_png(svg_content, out):
    # when settings.DEBUG is on (i.e. locally) don't delete the svgs.
    tmp_args = {
        'dir': settings.TMP_PATH, 'mode': 'wb', 'suffix': '.svg',
        'delete': not settings.DEBUG}
    with tempfile.NamedTemporaryFile(**tmp_args) as temporary_svg:
        temporary_svg.write(svg_content)
        temporary_svg.flush()

        try:
            if not os.path.exists(os.path.dirname(out)):
                os.makedirs(out)
            command = [
                settings.RSVG_CONVERT_BIN,
                '-o', out,
                temporary_svg.name
            ]
            subprocess.check_call(command)
        except IOError as io_error:
            log.debug(io_error)
            return False
        except subprocess.CalledProcessError as process_error:
            log.debug(process_error)
            return False
    return True


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
        self.alignment = (alignment or 'right top').lower()
        self.tiling = (tiling or 'no-repeat').lower()
        self.src, self.width, self.height = encode_header_image(
            os.path.join(header_root, path))

    def calculate_pattern_offsets(self, svg_width, svg_height):
        align_x, align_y = self.split_alignment(self.alignment)

        if align_x == 'right':
            self.pattern_x = svg_width - self.width
        elif align_x == 'center':
            self.pattern_x = (svg_width - self.width) / 2
        else:
            self.pattern_x = 0
        if align_y == 'bottom':
            self.pattern_y = svg_height - self.height
        elif align_y == 'center':
            self.pattern_y = (svg_height - self.height) / 2
        else:
            self.pattern_y = 0

        if self.tiling in ['repeat', 'repeat-x'] or self.width > svg_width:
            self.pattern_width = self.width
        else:
            self.pattern_width = svg_width
        if self.tiling in ['repeat', 'repeat-y'] or self.height > svg_height:
            self.pattern_height = self.height
        else:
            self.pattern_height = svg_height


CHROME_COLOR_TO_CSS = {
    'bookmark_text': 'toolbar_text',
    'frame': 'accentcolor',
    'frame_inactive': 'accentcolor',
    'tab_background_text': 'textcolor',
}


def process_color_value(prop, value):
    prop = CHROME_COLOR_TO_CSS.get(prop, prop)
    if isinstance(value, list) and len(value) == 3:
        return prop, u'rgb(%s, %s, %s)' % tuple(value)
    return prop, unicode(value)
