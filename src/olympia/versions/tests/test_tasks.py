import math
import os
import tempfile
from base64 import b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest
from PIL import Image, ImageChops

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.versions.models import VersionPreview
from olympia.versions.tasks import (
    AdditionalBackground, generate_static_theme_preview, write_svg_to_png)


def test_write_svg_to_png():
    out = tempfile.mktemp()
    svg_xml = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/weta_theme.svg')
    svg_png = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/weta_theme.png')
    with storage.open(svg_xml, 'rb') as svgfile:
        svg = svgfile.read()
    write_svg_to_png(svg, out)
    assert storage.exists(out)
    # compare the image content. rms should be 0 but travis renders it
    # different... 19 is the magic difference.
    svg_png_img = Image.open(svg_png)
    svg_out_img = Image.open(out)
    image_diff = ImageChops.difference(svg_png_img, svg_out_img)
    sum_of_squares = sum(
        value * ((idx % 256) ** 2)
        for idx, value in enumerate(image_diff.histogram()))
    rms = math.sqrt(
        sum_of_squares / float(svg_png_img.size[0] * svg_png_img.size[1]))

    assert rms < 19


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@pytest.mark.parametrize(
    'header_url, header_height, preserve_aspect_ratio, mimetype, valid_img', (
        ('transparent.gif', 1, 'xMaxYMin meet', 'image/gif', True),
        ('weta.png', 200, 'xMaxYMin meet', 'image/png', True),
        ('wetalong.png', 200, 'xMaxYMin slice', 'image/png', True),
        ('missing_file.png', 0, 'xMaxYMin meet', '', False),
        ('empty-no-ext', 10, 'xMaxYMin meet', 'image/png', True),
        (None, 0, 'xMaxYMin meet', '', False),  # i.e. no headerURL entry
    )
)
def test_generate_static_theme_preview(
        write_svg_to_png_mock, pngcrush_image_mock, resize_image_mock,
        header_url, header_height, preserve_aspect_ratio, mimetype, valid_img):
    write_svg_to_png_mock.return_value = (789, 101112)
    resize_image_mock.return_value = (123, 456), (789, 101112)
    theme_manifest = {
        "images": {
        },
        "colors": {
            "accentcolor": "#918e43",
            "textcolor": "#3deb60",
            "toolbar_text": "#b5ba5b",
            "toolbar_field": "#cc29cc",
            "toolbar_field_text": "#17747d"
        }
    }
    if header_url is not None:
        theme_manifest['images']['headerURL'] = header_url
    header_root = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/')
    addon = addon_factory()
    preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, header_root, preview)

    write_svg_to_png_mock.call_count == 1
    assert pngcrush_image_mock.call_count == 1
    assert pngcrush_image_mock.call_args_list[0][0][0] == preview.image_path
    ((svg_content, png_path), _) = write_svg_to_png_mock.call_args
    assert png_path == preview.image_path
    assert resize_image_mock.call_count == 1
    assert resize_image_mock.call_args_list[0][0] == (
        png_path,
        preview.thumbnail_path,
        amo.ADDON_PREVIEW_SIZES[0],
    )

    preview.reload()
    assert preview.sizes == {'image': [789, 101112], 'thumbnail': [123, 456]}

    # check header is there.
    assert 'width="680" height="100" xmlns="http://www.w3.org/2000/' in (
        svg_content)
    # check image xml is correct
    image_tag = (
        '<image id="svg-header-img" width="680" height="%s" '
        'preserveAspectRatio="%s"' % (header_height, preserve_aspect_ratio))
    assert image_tag in svg_content, svg_content
    # and image content is included and was encoded
    if valid_img:
        with storage.open(header_root + header_url, 'rb') as header_file:
            header_blob = header_file.read()
            base_64_uri = 'data:%s;base64,%s' % (
                mimetype, b64encode(header_blob))
    else:
        base_64_uri = ''
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content, svg_content
    # check each of our colors above was included
    for (key, color) in theme_manifest['colors'].items():
        snippet = 'class="%s" fill="%s"' % (key, color)
        assert snippet in svg_content


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
def test_generate_preview_with_additional_backgrounds(
        write_svg_to_png_mock, pngcrush_image_mock, resize_image_mock,):
    write_svg_to_png_mock.return_value = (789, 101112)
    resize_image_mock.return_value = (123, 456), (789, 101112)

    theme_manifest = {
        "images": {
            "headerURL": "empty.png",
            "additional_backgrounds": ["weta_for_tiling.png"],
        },
        "colors": {
            "accentcolor": "#918e43",
            "textcolor": "#3deb60",
        },
        "properties": {
            "additional_backgrounds_alignment": ["top"],
            "additional_backgrounds_tiling": ["repeat-x"],
        },
    }
    header_root = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/')
    addon = addon_factory()
    preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, header_root, preview)

    write_svg_to_png_mock.call_count == 1
    assert pngcrush_image_mock.call_count == 1
    assert pngcrush_image_mock.call_args_list[0][0][0] == preview.image_path
    ((svg_content, png_path), _) = write_svg_to_png_mock.call_args
    assert png_path == preview.image_path
    assert resize_image_mock.call_count == 1
    assert resize_image_mock.call_args_list[0][0] == (
        png_path,
        preview.thumbnail_path,
        amo.ADDON_PREVIEW_SIZES[0],
    )

    preview.reload()
    assert preview.sizes == {'image': [789, 101112], 'thumbnail': [123, 456]}

    # check additional background pattern is correct
    image_width = 270
    image_height = 200
    pattern_x_offset = (680 - image_width) / 2
    pattern_tag = (
        '<pattern id="AdditionalBackground1"\n'
        '                   width="%s" height="%s"\n'
        '                   x="%s" y="%s" patternUnits="userSpaceOnUse">' % (
            image_width, '100%', pattern_x_offset, 0))
    assert pattern_tag in svg_content, svg_content
    image_tag = '<image width="%s" height="%s"' % (image_width, image_height)
    assert image_tag in svg_content, svg_content
    rect_tag = (
        '<rect width="100%" height="100%" fill="url(#AdditionalBackground1)">'
        '</rect>')
    assert rect_tag in svg_content, svg_content
    # and image content is included and was encoded
    additional = os.path.join(header_root, 'weta_for_tiling.png')
    with storage.open(additional, 'rb') as header_file:
        header_blob = header_file.read()
    base_64_uri = 'data:%s;base64,%s' % ('image/png', b64encode(header_blob))
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content


@pytest.mark.parametrize(
    'alignment, alignments_tuple', (
        ('center bottom', ('center', 'bottom')),
        ('top', ('center', 'top')),
        ('center', ('center', 'center')),
        ('left', ('left', 'center')),
        ('', ('', ''))
    )
)
def test_additional_background_split_alignment(alignment, alignments_tuple):
    assert AdditionalBackground.split_alignment(alignment) == alignments_tuple


@mock.patch('olympia.versions.tasks.encode_header_image')
@pytest.mark.parametrize(
    'alignment, tiling,'  # inputs
    'pattern_width, pattern_height, pattern_x, pattern_y', (
        ('center bottom', 'no-repeat', '100%', '100%', 280, -350),
        ('top', 'repeat-x', 120, '100%', 280, 0),
        ('center', 'repeat-y', '100%', 450, 280, -175),
        ('left top', 'repeat', 120, 450, 0, 0),
        # alignment=None is 'left top'
        (None, 'repeat', 120, 450, 0, 0),
        # tiling=None is 'no-repeat'
        ('center', None, '100%', '100%', 280, -175),
        (None, None, '100%', '100%', 0, 0),
    )
)
def test_additional_background(encode_header_image, alignment, tiling,
                               pattern_width, pattern_height, pattern_x,
                               pattern_y):
    encode_header_image.return_value = ('foobaa', 120, 450)
    path = 'empty.png'
    header_root = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/')
    background = AdditionalBackground(path, alignment, tiling, header_root)
    assert background.src == 'foobaa'
    assert background.width == 120
    assert background.height == 450
    assert background.pattern_width == pattern_width
    assert background.pattern_height == pattern_height
    assert background.pattern_x == pattern_x
    assert background.pattern_y == pattern_y
