import math
import os
import shutil
import tempfile
from base64 import b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest
from PIL import Image, ImageChops

from olympia.addons.models import Preview
from olympia.amo.tests import addon_factory
from olympia.versions.tasks import (
    generate_static_theme_preview, write_svg_to_png)


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
    # different... 960 is the magic difference.
    svg_png_img = Image.open(svg_png)
    svg_out_img = Image.open(out)
    image_diff = ImageChops.difference(svg_png_img, svg_out_img)
    sum_of_squares = sum(
        value * ((idx % 256) ** 2)
        for idx, value in enumerate(image_diff.histogram()))
    rms = math.sqrt(
        sum_of_squares / float(svg_png_img.size[0] * svg_png_img.size[1]))

    assert rms == 0


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@pytest.mark.parametrize(
    'header_url, header_height, preserve_aspect_ratio, mimetype', (
        ('transparent.gif', 1, 'xMaxYMin meet', 'image/gif'),
        ('weta.png', 200, 'xMaxYMin meet', 'image/png'),
        ('wetalong.png', 200, 'xMaxYMin slice', 'image/png'),
    )
)
def test_generate_static_theme_preview(
        write_svg_to_png, header_url, header_height, preserve_aspect_ratio,
        mimetype):
    write_svg_to_png.return_value = (123, 456)
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
    preview = Preview.objects.create(addon=addon)
    generate_static_theme_preview(theme_manifest, header_root, preview)
    write_svg_to_png.assert_called()
    ((svg_content, png_path), _) = write_svg_to_png.call_args
    assert png_path == preview.image_path
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
