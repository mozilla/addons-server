import math
import os
import shutil
import tempfile
from base64 import b64encode
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.utils.encoding import force_str

import pytest
from freezegun import freeze_time
from PIL import Image, ImageChops

from olympia import amo
from olympia.amo.tests import root_storage
from olympia.constants.reviewers import EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY
from olympia.zadmin.models import Config

from ..utils import (
    AdditionalBackground,
    encode_header,
    get_review_due_date,
    get_staggered_review_due_date_generator,
    process_color_value,
    write_svg_to_png,
)


@pytest.mark.parametrize('filename', (('weta_theme_firefox'), ('weta_theme_amo')))
def test_write_svg_to_png(filename):
    # If you want to regenerate these, e.g. the svg template has significantly
    # changed, you can grab the svg file from shared_storage/tmp - when
    # settings.DEBUG==True it's not deleted afterwards.
    # Output png files are in shared_storage/uploads/version-previews/full
    # and /thumbs.
    svg_xml = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/%s.svg' % filename
    )
    svg_png = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/%s.png' % filename
    )
    with root_storage.open(svg_xml, 'rb') as svgfile:
        svg = svgfile.read()
    try:
        out_dir = tempfile.mkdtemp(dir=settings.TMP_PATH)
        out = os.path.join(out_dir, 'a', 'b.png')
        write_svg_to_png(svg, out)
        assert root_storage.exists(out)
        # compare the image content. rms should be 0 but CI renders it
        # different... 3 is the magic difference.
        svg_png_img = Image.open(svg_png)
        svg_out_img = Image.open(out)
        image_diff = ImageChops.difference(svg_png_img, svg_out_img)
    except Exception as e:
        raise e
    finally:
        shutil.rmtree(out_dir)
    sum_of_squares = sum(
        value * ((idx % 256) ** 2) for idx, value in enumerate(image_diff.histogram())
    )
    rms = math.sqrt(sum_of_squares / float(svg_png_img.size[0] * svg_png_img.size[1]))

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


@mock.patch('olympia.versions.utils.encode_header')
@pytest.mark.parametrize(
    'alignment, tiling, image_width, image_height, '  # inputs
    'pattern_width, pattern_height, pattern_x, pattern_y',  # results
    (
        # these are all with a small image than the svg size
        ('center bottom', 'no-repeat', 120, 50, 680, 92, 280, 42),
        ('top', 'repeat-x', 120, 50, 120, 92, 280, 0),
        ('center', 'repeat-y', 120, 50, 680, 50, 280, 21),
        ('left top', 'repeat', 120, 50, 120, 50, 0, 0),
        # alignment=None is 'right top'
        (None, 'repeat', 120, 50, 120, 50, 560, 0),
        # tiling=None is 'no-repeat'
        ('center', None, 120, 50, 680, 92, 280, 21),
        # so this is alignment='right top'; tiling='no-repeat'
        (None, None, 120, 50, 680, 92, 560, 0),
        # repeat with a larger image than the svg size
        ('center bottom', 'no-repeat', 1120, 450, 1120, 450, -220, -358),
        ('top', 'repeat-x', 1120, 450, 1120, 450, -220, 0),
        ('center', 'repeat-y', 1120, 450, 1120, 450, -220, -179),
        ('left top', 'repeat', 1120, 450, 1120, 450, 0, 0),
        # alignment=None is 'right top'
        (None, 'repeat', 1120, 450, 1120, 450, -440, 0),
        # tiling=None is 'no-repeat'
        ('center', None, 1120, 450, 1120, 450, -220, -179),
        # so this is alignment='right top'; tiling='no-repeat'
        (None, None, 1120, 450, 1120, 450, -440, 0),
    ),
)
def test_additional_background(
    encode_header_mock,
    alignment,
    tiling,
    image_width,
    image_height,
    pattern_width,
    pattern_height,
    pattern_x,
    pattern_y,
):
    encode_header_mock.return_value = ('foobaa', image_width, image_height)
    path = 'empty.png'
    background = AdditionalBackground(path, alignment, tiling, None)
    assert background.src == 'foobaa'
    assert background.width == image_width
    assert background.height == image_height
    background.calculate_pattern_offsets(
        amo.THEME_PREVIEW_RENDERINGS['firefox']['full'].width,
        amo.THEME_PREVIEW_RENDERINGS['firefox']['full'].height,
    )
    assert background.pattern_width == pattern_width
    assert background.pattern_height == pattern_height
    assert background.pattern_x == pattern_x
    assert background.pattern_y == pattern_y


@pytest.mark.parametrize(
    'manifest_property, manifest_color, firefox_prop, css_color',
    (
        ('bookmark_text', [2, 3, 4], 'bookmark_text', 'rgb(2,3,4)'),
        ('frame', [12, 13, 14], 'frame', 'rgb(12,13,14)'),
        ('textcolor', 'rgb(32,33,34)', 'tab_background_text', 'rgb(32,33,34)'),
        ('accentcolor', 'rgb(42, 43, 44)', 'frame', 'rgb(42,43,44)'),
        ('toolbar_text', 'rgb(42,43,44)', 'bookmark_text', 'rgb(42,43,44)'),
    ),
)
def test_process_color_value(
    manifest_property, manifest_color, firefox_prop, css_color
):
    assert (firefox_prop, css_color) == (
        process_color_value(manifest_property, manifest_color)
    )


def test_encode_header():
    svg_encoded = 'data:image/{};base64,{}'
    svg_blob = b"""

<svg id="preview-svg-root" width="680" height="92" xmlns="http://www.w3.org/2000/svg"
    """
    assert encode_header(svg_blob, '.svg') == (
        svg_encoded.format('svg+xml', force_str(b64encode(svg_blob))),
        680,
        92,
    )

    svg_blob_rev = b'<svg id="preview-svg-root" height="92" width="680" xmlns="'
    assert encode_header(svg_blob_rev, '.svg') == (
        svg_encoded.format('svg+xml', force_str(b64encode(svg_blob_rev))),
        680,
        92,
    )

    svg_blob_missing_height = b'<svg id="preview-svg-root" width="680" xmlns="'
    assert encode_header(svg_blob_missing_height, '.svg') == (None, 0, 0)

    svg_blob_missing_width = b'<svg id="preview-svg-root" height="92" xmlns="'
    assert encode_header(svg_blob_missing_width, '.svg') == (None, 0, 0)


def test_get_review_due_date():
    # it's a Monday, so due on Thursday
    assert get_review_due_date(datetime(2022, 12, 5, 6)) == datetime(2022, 12, 8, 6)
    # it's a Tuesday, so due on Friday
    assert get_review_due_date(datetime(2022, 12, 6, 10)) == datetime(2022, 12, 9, 10)
    # it's a Wednesday, but weekend in between so due on Monday
    assert get_review_due_date(datetime(2022, 12, 7, 15)) == datetime(2022, 12, 12, 15)
    # it's a Thursday, but weekend in between so due on Tuesday
    assert get_review_due_date(datetime(2022, 12, 8, 8)) == datetime(2022, 12, 13, 8)
    # it's a Friday, but weekend in between so due on Wednesday
    assert get_review_due_date(datetime(2022, 12, 9, 13)) == datetime(2022, 12, 14, 13)
    # it's a Saturday, but its not a working day so treat as Monday 9am, due on Thursday
    assert get_review_due_date(datetime(2022, 12, 10, 0)) == datetime(2022, 12, 15, 9)
    # it's a Sunday, but its not a working day so treat as Monday 0am, due on Thursday
    assert get_review_due_date(datetime(2022, 12, 11, 23)) == datetime(2022, 12, 15, 9)
    # for completeness check a Monday again
    assert get_review_due_date(datetime(2022, 12, 12)) == datetime(2022, 12, 15)

    # Pass different default
    # it's a Monday, so due on Friday
    assert get_review_due_date(datetime(2022, 12, 5, 6), default_days=4) == datetime(
        2022, 12, 9, 6
    )
    # it's a Tuesday, so due on Monday because of week-end.
    assert get_review_due_date(datetime(2022, 12, 6, 10), default_days=4) == datetime(
        2022, 12, 12, 10
    )


@freeze_time('2023-05-22 11:00')
def test_get_review_due_date_default_starting_date_now():
    assert get_review_due_date() == datetime(2023, 5, 25, 11, 0)


@freeze_time('2023-05-16 11:00')
@pytest.mark.django_db
def test_get_staggered_review_due_date_generator():
    # Default config is to start from now + REVIEWER_STANDARD_REVIEW_TIME, and
    # do 8 (arbitrary, gotta pick a number) reviews per day.
    generator = get_staggered_review_due_date_generator()
    due = next(generator)
    assert due == datetime(2023, 5, 19, 11, 0)

    # 8 per day means next target is 3 hours later (24 / 8)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 14, 0)

    # Skip the week-end (would otherwise land on Saturday 20th).
    for _x in range(0, 4):
        due = next(generator)
    assert due == datetime(2023, 5, 22, 2, 0)

    # Should have 7 more on that Monday.
    for _x in range(0, 7):
        due = next(generator)
    assert due == datetime(2023, 5, 22, 23, 0)

    # Check we aren't putting any more on Monday.
    due = next(generator)
    assert due == datetime(2023, 5, 23, 2, 0)


@freeze_time('2023-05-16 11:00')
def test_get_staggered_review_due_date_generator_default_target_provided():
    generator = get_staggered_review_due_date_generator(target_per_day=2)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 11, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 23, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 22, 11, 0)


@freeze_time('2023-05-19 11:00')
def test_get_staggered_review_due_date_generator_default_initial_days_delay():
    generator = get_staggered_review_due_date_generator(
        initial_days_delay=2, target_per_day=8
    )
    due = next(generator)
    assert due == datetime(2023, 5, 23, 11, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 23, 14, 0)


def test_get_staggered_review_due_date_generator_default_initial_starting_date():
    generator = get_staggered_review_due_date_generator(
        starting=datetime(2023, 5, 22, 11, 0), target_per_day=1
    )
    due = next(generator)
    assert due == datetime(2023, 5, 25, 11, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 26, 11, 0)


@freeze_time('2023-05-16 11:00')
@pytest.mark.django_db
def test_get_staggered_review_due_date_generator_custom_config():
    Config.objects.create(key=EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY, value='4')
    generator = get_staggered_review_due_date_generator()
    due = next(generator)
    assert due == datetime(2023, 5, 19, 11, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 17, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 23, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 22, 5, 0)


@mock.patch('olympia.zadmin.models.log')
@freeze_time('2023-05-16 11:00')
@pytest.mark.django_db
def test_get_staggered_review_due_date_generator_garbage_config(log_mock):
    Config.objects.create(key=EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY, value='lolweird')
    generator = get_staggered_review_due_date_generator()

    # Falls back on arbitrary default (8), logging an error. So next due date
    # after initial should be in 3 hours.
    due = next(generator)
    assert due == datetime(2023, 5, 19, 11, 0)
    due = next(generator)
    assert due == datetime(2023, 5, 19, 14, 0)

    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'extra-review-target-per-day',
        'lolweird',
    )
