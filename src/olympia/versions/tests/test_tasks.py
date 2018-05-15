import os
from base64 import b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.versions.models import VersionPreview
from olympia.versions.tasks import generate_static_theme_preview


HEADER_ROOT = os.path.join(
    settings.ROOT, 'src/olympia/versions/tests/static_themes/')


def check_render(svg_content, header_url, header_height, preserve_aspect_ratio,
                 mimetype, valid_img, colors, svg_width,
                 svg_height, inner_width):
    # check header is there.
    assert 'width="%s" height="%s" xmlns="http://www.w3.org/2000/' % (
        svg_width, svg_height) in svg_content
    # check image xml is correct
    image_tag = (
        '<image id="svg-header-img" width="%s" height="%s" '
        'preserveAspectRatio="%s"' % (
            inner_width, header_height, preserve_aspect_ratio))
    assert image_tag in svg_content, svg_content
    # and image content is included and was encoded
    if valid_img:
        with storage.open(HEADER_ROOT + header_url, 'rb') as header_file:
            header_blob = header_file.read()
            base_64_uri = 'data:%s;base64,%s' % (
                mimetype, b64encode(header_blob))
    else:
        base_64_uri = ''
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content, svg_content
    # check each of our colors above was included
    for color in colors:
        assert color in svg_content


@pytest.mark.django_db
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
        write_svg_to_png_mock, pngcrush_image_mock,
        header_url, header_height, preserve_aspect_ratio, mimetype, valid_img):
    write_svg_to_png_mock.return_value = True
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
    addon = addon_factory()
    preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, HEADER_ROOT, preview)

    write_svg_to_png_mock.call_count == 2
    (image_svg_content, png_path) = write_svg_to_png_mock.call_args_list[0][0]
    assert png_path == preview.image_path
    (thumb_svg_content, png_path) = write_svg_to_png_mock.call_args_list[1][0]
    assert png_path == preview.thumbnail_path

    assert pngcrush_image_mock.call_count == 2
    assert pngcrush_image_mock.call_args_list[0][0][0] == preview.image_path
    assert pngcrush_image_mock.call_args_list[1][0][0] == (
        preview.thumbnail_path)

    preview.reload()
    assert preview.sizes == {
        'image': list(amo.THEME_PREVIEW_SIZES['full']),
        'thumbnail': list(amo.THEME_PREVIEW_SIZES['thumb'])}

    colors = ['class="%s" fill="%s"' % (key, color)
              for (key, color) in theme_manifest['colors'].items()]

    check_render(image_svg_content, header_url, header_height,
                 preserve_aspect_ratio, mimetype, valid_img, colors,
                 680, 92, 680)
    check_render(thumb_svg_content, header_url, header_height,
                 preserve_aspect_ratio, mimetype, valid_img, colors,
                 670, 64, 963.125)


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
def test_generate_static_theme_preview_with_chrome_properties(
        write_svg_to_png_mock, pngcrush_image_mock):
    write_svg_to_png_mock.return_value = True
    theme_manifest = {
        "images": {
            "theme_frame": "transparent.gif"
        },
        "colors": {
            "frame": [123, 45, 67],  # 'accentcolor'
            "tab_background_text": [9, 87, 65],  # 'textcolor'
            "bookmark_text": [0, 0, 0],  # 'toolbar_text'
        }
    }
    addon = addon_factory()
    preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, HEADER_ROOT, preview)

    write_svg_to_png_mock.call_count == 2
    (image_svg_content, png_path) = write_svg_to_png_mock.call_args_list[0][0]
    assert png_path == preview.image_path
    (thumb_svg_content, png_path) = write_svg_to_png_mock.call_args_list[1][0]
    assert png_path == preview.thumbnail_path

    assert pngcrush_image_mock.call_count == 2
    assert pngcrush_image_mock.call_args_list[0][0][0] == preview.image_path
    assert pngcrush_image_mock.call_args_list[1][0][0] == (
        preview.thumbnail_path)

    preview.reload()
    assert preview.sizes == {
        'image': list(amo.THEME_PREVIEW_SIZES['full']),
        'thumbnail': list(amo.THEME_PREVIEW_SIZES['thumb'])}

    colors = []
    # check each of our colors above was converted to css codes
    chrome_colors = {
        'bookmark_text': 'toolbar_text',
        'frame': 'accentcolor',
        'tab_background_text': 'textcolor',
    }
    for (chrome_prop, firefox_prop) in chrome_colors.items():
        color_list = theme_manifest['colors'][chrome_prop]
        color = 'rgb(%s, %s, %s)' % tuple(color_list)
        colors.append('class="%s" fill="%s"' % (firefox_prop, color))

    check_render(image_svg_content, 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 680, 92, 680)
    check_render(thumb_svg_content, 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 670, 64, 963.125)


def check_render_additional(svg_content, inner_svg_width):
    # check additional background pattern is correct
    image_width = 270
    image_height = 200
    pattern_x_offset = (inner_svg_width - image_width) / 2
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
    additional = os.path.join(HEADER_ROOT, 'weta_for_tiling.png')
    with storage.open(additional, 'rb') as header_file:
        header_blob = header_file.read()
    base_64_uri = 'data:%s;base64,%s' % ('image/png', b64encode(header_blob))
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
def test_generate_preview_with_additional_backgrounds(
        write_svg_to_png_mock, pngcrush_image_mock):
    write_svg_to_png_mock.return_value = True

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
    addon = addon_factory()
    preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, HEADER_ROOT, preview)

    write_svg_to_png_mock.call_count == 2
    (image_svg_content, png_path) = write_svg_to_png_mock.call_args_list[0][0]
    assert png_path == preview.image_path
    (thumb_svg_content, png_path) = write_svg_to_png_mock.call_args_list[1][0]
    assert png_path == preview.thumbnail_path

    assert pngcrush_image_mock.call_count == 2
    assert pngcrush_image_mock.call_args_list[0][0][0] == preview.image_path
    assert pngcrush_image_mock.call_args_list[1][0][0] == (
        preview.thumbnail_path)

    preview.reload()
    assert preview.sizes == {
        'image': list(amo.THEME_PREVIEW_SIZES['full']),
        'thumbnail': list(amo.THEME_PREVIEW_SIZES['thumb'])}

    check_render_additional(image_svg_content, 680)
    check_render_additional(thumb_svg_content, 963.125)
