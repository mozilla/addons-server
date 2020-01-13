import json
import math
import os
import shutil
import tempfile
import zipfile

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

from unittest import mock
import pytest
from PIL import Image, ImageChops

from olympia import amo, core
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.files.tests.test_utils import AppVersionsMixin
from olympia.versions.utils import (
    AdditionalBackground, new_69_theme_properties_from_old,
    new_theme_version_with_69_properties, process_color_value, write_svg_to_png
)


@pytest.mark.parametrize(
    'filename', (('weta_theme_full'), ('weta_theme_list'))
)
def test_write_svg_to_png(filename):
    # If you want to regenerate these, e.g. the svg template has significantly
    # changed, you can grab the svg file from shared_storage/tmp - when
    # settings.DEBUG==True it's not deleted afterwards.
    # Output png files are in shared_storage/uploads/version-previews/full
    # and /thumbs.
    svg_xml = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/%s.svg' % filename)
    svg_png = os.path.join(
        settings.ROOT,
        'src/olympia/versions/tests/static_themes/%s.png' % filename)
    with storage.open(svg_xml, 'rb') as svgfile:
        svg = svgfile.read()
    try:
        out_dir = tempfile.mkdtemp()
        out = os.path.join(out_dir, 'a', 'b.png')
        write_svg_to_png(svg, out)
        assert storage.exists(out)
        # compare the image content. rms should be 0 but travis renders it
        # different... 3 is the magic difference.
        svg_png_img = Image.open(svg_png)
        svg_out_img = Image.open(out)
        image_diff = ImageChops.difference(svg_png_img, svg_out_img)
    except Exception as e:
        raise e
    finally:
        shutil.rmtree(out_dir)
    sum_of_squares = sum(
        value * ((idx % 256) ** 2)
        for idx, value in enumerate(image_diff.histogram()))
    rms = math.sqrt(
        sum_of_squares / float(svg_png_img.size[0] * svg_png_img.size[1]))

    assert rms < 3


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


@mock.patch('olympia.versions.utils.encode_header')
@pytest.mark.parametrize(
    'alignment, tiling, image_width, image_height, '  # inputs
    'pattern_width, pattern_height, pattern_x, pattern_y',  # results
    (
        # these are all with a small image than the svg size
        ('center bottom', 'no-repeat', 120, 50,
         680, 92, 280, 42),
        ('top', 'repeat-x', 120, 50,
         120, 92, 280, 0),
        ('center', 'repeat-y', 120, 50,
         680, 50, 280, 21),
        ('left top', 'repeat', 120, 50,
         120, 50, 0, 0),
        # alignment=None is 'right top'
        (None, 'repeat', 120, 50,
         120, 50, 560, 0),
        # tiling=None is 'no-repeat'
        ('center', None, 120, 50,
         680, 92, 280, 21),
        # so this is alignment='right top'; tiling='no-repeat'
        (None, None, 120, 50,
         680, 92, 560, 0),

        # repeat with a larger image than the svg size
        ('center bottom', 'no-repeat', 1120, 450,
         1120, 450, -220, -358),
        ('top', 'repeat-x', 1120, 450,
         1120, 450, -220, 0),
        ('center', 'repeat-y', 1120, 450,
         1120, 450, -220, -179),
        ('left top', 'repeat', 1120, 450,
         1120, 450, 0, 0),
        # alignment=None is 'right top'
        (None, 'repeat', 1120, 450,
         1120, 450, -440, 0),
        # tiling=None is 'no-repeat'
        ('center', None, 1120, 450,
         1120, 450, -220, -179),
        # so this is alignment='right top'; tiling='no-repeat'
        (None, None, 1120, 450,
         1120, 450, -440, 0),
    )
)
def test_additional_background(
        encode_header_mock, alignment, tiling, image_width, image_height,
        pattern_width, pattern_height, pattern_x, pattern_y):
    encode_header_mock.return_value = (
        'foobaa', image_width, image_height)
    path = 'empty.png'
    background = AdditionalBackground(path, alignment, tiling, None)
    assert background.src == 'foobaa'
    assert background.width == image_width
    assert background.height == image_height
    background.calculate_pattern_offsets(
        amo.THEME_PREVIEW_SIZES['header']['full'].width,
        amo.THEME_PREVIEW_SIZES['header']['full'].height)
    assert background.pattern_width == pattern_width
    assert background.pattern_height == pattern_height
    assert background.pattern_x == pattern_x
    assert background.pattern_y == pattern_y


@pytest.mark.parametrize(
    'manifest_property, manifest_color, firefox_prop, css_color', (
        ('bookmark_text', [2, 3, 4], 'bookmark_text', 'rgb(2,3,4)'),
        ('frame', [12, 13, 14], 'frame', 'rgb(12,13,14)'),
        ('textcolor', 'rgb(32,33,34)', 'tab_background_text', 'rgb(32,33,34)'),
        ('accentcolor', 'rgb(42, 43, 44)', 'frame', 'rgb(42,43,44)'),
        ('toolbar_text', 'rgb(42,43,44)', 'bookmark_text', 'rgb(42,43,44)'),
    )
)
def test_process_color_value(manifest_property, manifest_color, firefox_prop,
                             css_color):
    assert (firefox_prop, css_color) == (
        process_color_value(manifest_property, manifest_color))


class TestNew69ThemeProperties(AppVersionsMixin, TestCase):
    file_obj_dep = os.path.join(
        settings.ROOT,
        'src/olympia/devhub/tests/addons/static_theme_deprecated.zip')

    def setUp(self):
        self.call_signing_mock = self.patch(
            'olympia.lib.crypto.signing.call_signing')
        self.call_signing_mock.return_value = 'abcdefg1234'

    def test_new_69_theme_properties_from_old(self):
        old = {
            'theme': {
                'colors': {
                    'accentcolor': '#dfa672',
                    'textcolor': '#fff',
                    'toolbar_text': 'rgb(0,12,34)',
                },
                'images': {
                    'headerURL': 'path/to/image'
                }
            }
        }
        new_ = new_69_theme_properties_from_old(old)
        assert new_ == {
            'theme': {
                'colors': {
                    'frame': '#dfa672',
                    'tab_background_text': '#fff',
                    'bookmark_text': 'rgb(0,12,34)',
                },
                'images': {
                    'theme_frame': 'path/to/image'
                }
            }
        }

    def test_new_69_theme_properties_from_old_no_overwrite(self):
        old = {
            'theme': {
                'colors': {
                    'accentcolor': '#dfa672',
                    'textcolor': '#fff',
                    'toolbar_text': 'rgb(0,12,34)',
                    'frame': '#672',
                    'tab_background_text': '#eee',
                    'bookmark_text': 'rgb()',
                },
                'images': {
                    'headerURL': 'path/to/image',
                    'theme_frame': 'path/to/otherimage',
                }
            }
        }
        new_ = new_69_theme_properties_from_old(old)
        assert new_ == old

    @override_settings(ENABLE_ADDON_SIGNING=True)
    def test_new_theme_version_with_69_properties(self):
        core.set_user(user_factory())

        addon = addon_factory(
            type=amo.ADDON_STATICTHEME, version_kw={'version': '1.0'})
        old_version = addon.current_version
        old_file_path = old_version.all_files[0].current_file_path
        amo.storage_utils.copy_stored_file(self.file_obj_dep, old_file_path)
        assert os.path.isfile(old_file_path)

        new_version = new_theme_version_with_69_properties(old_version)
        assert addon.versions.all().count() == 2
        assert addon.current_version == new_version

        new_file_path = new_version.all_files[0].current_file_path
        with zipfile.ZipFile(self.file_obj_dep, 'r') as old_xpi:
            with zipfile.ZipFile(new_file_path, 'r') as new_xpi:
                assert len(old_xpi.infolist()) == len(new_xpi.infolist())
                for entry in old_xpi.infolist():
                    file_ = entry.filename
                    if file_ == 'manifest.json':
                        old_manifest = json.loads(old_xpi.read(file_))
                        new_manifest = json.loads(new_xpi.read(file_))
                        assert old_manifest != new_manifest
                        # need to pop the version as it's been bumped
                        old_ver_num = old_manifest.pop('version')
                        new_ver_num = new_manifest.pop('version')
                        assert old_ver_num != new_ver_num
                        assert new_manifest == (
                            new_69_theme_properties_from_old(old_manifest))

                    else:
                        assert old_xpi.read(file_) == new_xpi.read(file_)
