import os
import io
import re
import tempfile

from base64 import b64encode

from django.conf import settings
from django.utils.encoding import force_str

from PIL import Image

from olympia.amo.utils import convert_svg_to_png
from olympia.core import logger

from . import compare
from .models import Version


log = logger.getLogger('z.versions.utils')


def get_next_version_number(addon):
    if not addon:
        return '1.0'
    last_version = Version.unfiltered.filter(addon=addon).order_by('id').last()
    version_dict = compare.version_dict(last_version.version)

    version_counter = 1
    while True:
        next_version = '%s.0' % (version_dict['major'] + version_counter)
        if not Version.unfiltered.filter(addon=addon, version=next_version).exists():
            return next_version
        else:
            version_counter += 1


def write_svg_to_png(svg_content, out):
    # when settings.DEBUG is on (i.e. locally) don't delete the svgs.
    tmp_args = {
        'dir': settings.TMP_PATH,
        'mode': 'wb',
        'suffix': '.svg',
        'delete': not settings.DEBUG,
    }
    with tempfile.NamedTemporaryFile(**tmp_args) as temporary_svg:
        temporary_svg.write(svg_content)
        temporary_svg.flush()
        return convert_svg_to_png(temporary_svg.name, out)


SVG_DIMENSIONS_REGEX = rb'(?=.* width="(?P<width>\d+)")(?=.* height="(?P<height>\d+)")'


def encode_header(header_blob, file_ext):
    try:
        if file_ext == '.svg':
            dimensions = re.search(SVG_DIMENSIONS_REGEX, header_blob).groupdict()
            width = int(dimensions['width'])
            height = int(dimensions['height'])
            img_format = 'svg+xml'
        else:
            with Image.open(io.BytesIO(header_blob)) as header_image:
                (width, height) = header_image.size
                img_format = header_image.format.lower()
        src = 'data:image/{};base64,{}'.format(
            img_format,
            force_str(b64encode(header_blob)),
        )
    except (OSError, ValueError, TypeError, AttributeError) as err:
        log.info(err)
        return (None, 0, 0)
    return (src, width, height)


class AdditionalBackground:
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

    def __init__(self, path, alignment, tiling, background):
        # If there an unequal number of alignments or tiling to srcs the value
        # will be None so use defaults.
        self.alignment = (alignment or 'right top').lower()
        self.tiling = (tiling or 'no-repeat').lower()
        file_ext = os.path.splitext(path)[1]
        self.src, self.width, self.height = encode_header(background, file_ext)

    def calculate_pattern_offsets(self, svg_width, svg_height):
        align_x, align_y = self.split_alignment(self.alignment)

        if align_x == 'right':
            self.pattern_x = svg_width - self.width
        elif align_x == 'center':
            self.pattern_x = (svg_width - self.width) // 2
        else:
            self.pattern_x = 0
        if align_y == 'bottom':
            self.pattern_y = svg_height - self.height
        elif align_y == 'center':
            self.pattern_y = (svg_height - self.height) // 2
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


DEPRECATED_COLOR_TO_CSS = {
    'toolbar_text': 'bookmark_text',
    'accentcolor': 'frame',
    'textcolor': 'tab_background_text',
}


def process_color_value(prop, value):
    prop = DEPRECATED_COLOR_TO_CSS.get(prop, prop)
    if isinstance(value, list) and len(value) == 3:
        return prop, 'rgb(%s,%s,%s)' % tuple(value)
    # strip out spaces because jquery.minicolors chokes on them
    return prop, str(value).replace(' ', '')
