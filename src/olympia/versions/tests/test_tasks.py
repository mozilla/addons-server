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


def check_preview(preview_instance, theme_size_constant, write_svg_mock_args,
                  resize_image_mock_args, png_crush_mock_args):
    _, png_path = write_svg_mock_args

    assert png_path == preview_instance.image_path
    assert preview_instance.sizes == {
        'image': list(theme_size_constant['full']),
        'thumbnail': list(theme_size_constant['thumbnail'])
    }
    resize_path, thumb_path, thumb_size = resize_image_mock_args
    assert resize_path == png_path
    assert thumb_path == preview_instance.thumbnail_path
    assert thumb_size == theme_size_constant['thumbnail']
    assert png_crush_mock_args[0] == preview_instance.image_path


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
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
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock,
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
    generate_static_theme_preview(
        theme_manifest, HEADER_ROOT, addon.current_version.pk)

    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert pngcrush_image_mock.call_count == 2

    # First check the header Preview is good
    header_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['header']['position'])
    check_preview(
        header_preview, amo.THEME_PREVIEW_SIZES['header'],
        write_svg_to_png_mock.call_args_list[0][0],
        resize_image_mock.call_args_list[0][0],
        pngcrush_image_mock.call_args_list[0][0])

    # Then the list Preview
    list_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['list']['position'])
    check_preview(
        list_preview, amo.THEME_PREVIEW_SIZES['list'],
        write_svg_to_png_mock.call_args_list[1][0],
        resize_image_mock.call_args_list[1][0],
        pngcrush_image_mock.call_args_list[1][0])

    # Now check the svg renders
    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    colors = ['class="%s" fill="%s"' % (key, color)
              for (key, color) in theme_manifest['colors'].items()]
    check_render(header_svg, header_url, header_height,
                 preserve_aspect_ratio, mimetype, valid_img, colors,
                 680, 92, 680)
    check_render(list_svg, header_url, header_height,
                 preserve_aspect_ratio, mimetype, valid_img, colors,
                 760, 92, 760)


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
def test_generate_static_theme_preview_with_chrome_properties(
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock):
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
    generate_static_theme_preview(
        theme_manifest, HEADER_ROOT, addon.current_version.pk)

    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert pngcrush_image_mock.call_count == 2

    # First check the header Preview is good
    header_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['header']['position'])
    check_preview(
        header_preview, amo.THEME_PREVIEW_SIZES['header'],
        write_svg_to_png_mock.call_args_list[0][0],
        resize_image_mock.call_args_list[0][0],
        pngcrush_image_mock.call_args_list[0][0])

    # Then the list Preview
    list_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['list']['position'])
    check_preview(
        list_preview, amo.THEME_PREVIEW_SIZES['list'],
        write_svg_to_png_mock.call_args_list[1][0],
        resize_image_mock.call_args_list[1][0],
        pngcrush_image_mock.call_args_list[1][0])

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

    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    check_render(header_svg, 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 680, 92, 680)
    check_render(list_svg, 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 760, 92, 760)


def check_render_additional(svg_content, inner_svg_width):
    # check additional background pattern is correct
    image_width = 270
    image_height = 200
    pattern_x_offset = (inner_svg_width - image_width) / 2
    pattern_tag = (
        '<pattern id="AdditionalBackground1"\n'
        '                   width="%s" height="%s"\n'
        '                   x="%s" y="%s" patternUnits="userSpaceOnUse">' % (
            image_width, image_height, pattern_x_offset, 0))
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
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
def test_generate_preview_with_additional_backgrounds(
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock):
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
    generate_static_theme_preview(
        theme_manifest, HEADER_ROOT, addon.current_version.pk)

    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert pngcrush_image_mock.call_count == 2

    # First check the header Preview is good
    header_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['header']['position'])
    check_preview(
        header_preview, amo.THEME_PREVIEW_SIZES['header'],
        write_svg_to_png_mock.call_args_list[0][0],
        resize_image_mock.call_args_list[0][0],
        pngcrush_image_mock.call_args_list[0][0])

    # Then the list Preview
    list_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['list']['position'])
    check_preview(
        list_preview, amo.THEME_PREVIEW_SIZES['list'],
        write_svg_to_png_mock.call_args_list[1][0],
        resize_image_mock.call_args_list[1][0],
        pngcrush_image_mock.call_args_list[1][0])

    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    check_render_additional(header_svg, 680)
    check_render_additional(list_svg, 760)
