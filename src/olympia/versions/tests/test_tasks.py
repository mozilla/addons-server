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


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@pytest.mark.parametrize(
    'header_url, header_height, preserve_aspect_ratio, mimetype', (
        ('transparent.gif', 1, 'xMaxYMin meet', 'image/gif'),
        ('weta.png', 200, 'xMaxYMin meet', 'image/png'),
        ('wetalong.png', 200, 'xMaxYMin slice', 'image/png'),
    )
)
def test_generate_static_theme_preview(
        write_svg_to_png_mock, pngcrush_image_mock, resize_image_mock,
        header_url, header_height, preserve_aspect_ratio, mimetype):
    write_svg_to_png_mock.return_value = (789, 101112)
    resize_image_mock.return_value = (123, 456), (789, 101112)
    theme_manifest = {
        "images": {
            "headerURL": header_url
        },
        "colors": {
            "accentcolor": "#918e43",
            "textcolor": "#3deb60",
            "toolbar_text": "#b5ba5b",
            "toolbar_field": "#cc29cc",
            "toolbar_field_text": "#17747d"
        }
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

    # check header is there.
    assert 'width="680" height="100" xmlns="http://www.w3.org/2000/' in (
        svg_content)
    # check image xml is correct
    image_tag = (
        '<image id="svg-header-img" width="680" height="%s" '
        'preserveAspectRatio="%s"' % (header_height, preserve_aspect_ratio))
    assert image_tag in svg_content, svg_content
    # and image content is included and was encoded
    with storage.open(header_root + header_url, 'rb') as header_file:
        header_blob = header_file.read()
    base_64_uri = 'data:%s;base64,%s' % (mimetype, b64encode(header_blob))
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content
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
