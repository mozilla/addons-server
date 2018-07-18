import math
import os
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest
from PIL import Image, ImageChops

from olympia import amo
from olympia.versions.utils import (
    AdditionalBackground,
    process_color_value,
    write_svg_to_png,
)


@pytest.mark.parametrize(
    'filename', (('weta_theme_full'), ('weta_theme_list'))
)
def test_write_svg_to_png(filename):
    # If you want to regenerate these, e.g. the svg template has significantly
    # changed, easiest way is to patch write_svg_to_png to not delete the
    # temporary file (delete:False in temp_args) and copy the svg out of /tmp.
    # Output png files are in user-media/version-previews/full and /thumbs.
    out = tempfile.mktemp()
    svg_xml = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/%s.svg' % filename,
    )
    svg_png = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/%s.png' % filename,
    )
    with storage.open(svg_xml, 'rb') as svgfile:
        svg = svgfile.read()
    write_svg_to_png(svg, out)
    assert storage.exists(out)
    # compare the image content. rms should be 0 but travis renders it
    # different... 3 is the magic difference.
    svg_png_img = Image.open(svg_png)
    svg_out_img = Image.open(out)
    image_diff = ImageChops.difference(svg_png_img, svg_out_img)
    sum_of_squares = sum(
        value * ((idx % 256) ** 2)
        for idx, value in enumerate(image_diff.histogram())
    )
    rms = math.sqrt(
        sum_of_squares / float(svg_png_img.size[0] * svg_png_img.size[1])
    )

    assert rms < 3


@pytest.mark.parametrize(
    'alignment, alignments_tuple',
    (
        ('center bottom', ('center', 'bottom')),
        ('top', ('center', 'top')),
        ('center', ('center', 'center')),
        ('left', ('left', 'center')),
        ('', ('', '')),
    ),
)
def test_additional_background_split_alignment(alignment, alignments_tuple):
    assert AdditionalBackground.split_alignment(alignment) == alignments_tuple


@mock.patch('olympia.versions.utils.encode_header_image')
@pytest.mark.parametrize(
    'alignment, tiling,'  # inputs
    'pattern_width, pattern_height, pattern_x, pattern_y',
    (
        ('center bottom', 'no-repeat', '100%', '100%', 280, -358),
        ('top', 'repeat-x', 120, '100%', 280, 0),
        ('center', 'repeat-y', '100%', 450, 280, -179),
        ('left top', 'repeat', 120, 450, 0, 0),
        # alignment=None is 'left top'
        (None, 'repeat', 120, 450, 0, 0),
        # tiling=None is 'no-repeat'
        ('center', None, '100%', '100%', 280, -179),
        (None, None, '100%', '100%', 0, 0),
    ),
)
def test_additional_background(
    encode_header_image,
    alignment,
    tiling,
    pattern_width,
    pattern_height,
    pattern_x,
    pattern_y,
):
    encode_header_image.return_value = ('foobaa', 120, 450)
    path = 'empty.png'
    header_root = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/'
    )
    background = AdditionalBackground(path, alignment, tiling, header_root)
    assert background.src == 'foobaa'
    assert background.width == 120
    assert background.height == 450
    assert background.pattern_width == pattern_width
    assert background.pattern_height == pattern_height
    background.calculate_pattern_offsets(
        amo.THEME_PREVIEW_SIZES['header']['full'].width,
        amo.THEME_PREVIEW_SIZES['header']['full'].height,
    )
    assert background.pattern_x == pattern_x
    assert background.pattern_y == pattern_y


@pytest.mark.parametrize(
    'chrome_prop, chrome_color, firefox_prop, css_color',
    (
        ('bookmark_text', [2, 3, 4], 'toolbar_text', u'rgb(2, 3, 4)'),
        ('frame', [12, 13, 14], 'accentcolor', u'rgb(12, 13, 14)'),
        ('frame_inactive', [22, 23, 24], 'accentcolor', u'rgb(22, 23, 24)'),
        ('tab_background_text', [32, 33, 34], 'textcolor', u'rgb(32, 33, 34)'),
    ),
)
def test_process_color_value(
    chrome_prop, chrome_color, firefox_prop, css_color
):
    assert (firefox_prop, css_color) == (
        process_color_value(chrome_prop, chrome_color)
    )
