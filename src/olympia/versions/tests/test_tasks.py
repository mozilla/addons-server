import json
import os
import zipfile
from base64 import b64encode
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.utils.encoding import force_str

import pytest

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    root_storage,
    user_factory,
    version_factory,
)
from olympia.blocklist.models import Block, BlockType, BlockVersion
from olympia.reviewers.models import NeedsHumanReview

from ..models import Version, VersionPreview
from ..tasks import (
    UI_FIELDS,
    duplicate_addon_version_for_rollback,
    generate_static_theme_preview,
    hard_delete_versions,
    soft_block_versions,
)


HEADER_ROOT = os.path.join(settings.ROOT, 'src/olympia/versions/tests/static_themes/')

transparent_colors = [
    'class="%(field)s %(prop)s" %(prop)s="rgb(0,0,0,0)"'
    % {'field': field, 'prop': 'stroke' if field == 'tab_line' else 'fill'}
    for field in UI_FIELDS + ('tab_selected toolbar',)
    if field not in ('icons', 'tab_selected')  # bookmark_text class used instead
]


def check_render(
    svg_content,
    header_url,
    header_height,
    preserve_aspect_ratio,
    mimetype,
    valid_img,
    colors,
    svg_width,
    svg_height,
    inner_width,
):
    # check header is there.
    assert (
        'width="%s" height="%s" xmlns="http://www.w3.org/2000/'
        % (svg_width, svg_height)
        in svg_content
    )
    # check image xml is correct
    image_tag = (
        '<image id="svg-header-img" width="%s" height="%s" '
        'preserveAspectRatio="%s"' % (inner_width, header_height, preserve_aspect_ratio)
    )
    assert image_tag in svg_content, svg_content
    # and image content is included and was encoded
    if valid_img:
        with root_storage.open(HEADER_ROOT + header_url, 'rb') as header_file:
            header_blob = header_file.read()
            base_64_uri = 'data:{};base64,{}'.format(
                mimetype,
                force_str(b64encode(header_blob)),
            )
    else:
        base_64_uri = ''
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content, svg_content
    # check each of our colors above was included
    for color in colors:
        assert color in svg_content


def check_thumbnail(
    preview_instance,
    theme_size_constant,
    source_png_path,
    resize_image_mock_args_kwargs,
    png_crush_mock_args=None,
):
    (resize_path, thumb_path, thumb_size), resize_kwargs = resize_image_mock_args_kwargs
    assert resize_path == source_png_path
    assert thumb_path == preview_instance.thumbnail_path
    assert thumb_size == tuple(preview_instance.thumbnail_dimensions)
    if png_crush_mock_args:
        assert png_crush_mock_args[0] == source_png_path
    assert preview_instance.colors
    assert resize_kwargs == {
        'format': theme_size_constant['thumbnail_format'],
        'quality': 35,
    }


def check_preview(
    preview_instance,
    theme_size_constant,
):
    assert preview_instance.sizes == {
        'image': list(theme_size_constant['full']),
        'thumbnail': list(theme_size_constant['thumbnail']),
        'image_format': theme_size_constant['image_format'],
        'thumbnail_format': theme_size_constant['thumbnail_format'],
    }


def write_empty_png(svg_content, out):
    root_storage.copy_stored_file(os.path.join(HEADER_ROOT, 'empty.png'), out)
    return True


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
@mock.patch('olympia.versions.tasks.extract_colors_from_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@mock.patch('olympia.versions.tasks.convert_svg_to_png')
@pytest.mark.parametrize(
    'header_url, header_height, preserve_aspect_ratio, mimetype, valid_img',
    (
        ('transparent.gif', 1, 'xMaxYMin meet', 'image/gif', True),
        ('weta.png', 200, 'xMaxYMin meet', 'image/png', True),
        ('wetalong.png', 200, 'xMaxYMin slice', 'image/png', True),
        (
            'weta_theme_firefox.svg',
            92,  # different value for 680 and 760/720
            ('xMaxYMin slice', 'xMaxYMin meet'),
            'image/svg+xml',
            True,
        ),
        ('transparent.svg', 1, 'xMaxYMin meet', 'image/svg+xml', True),
        ('missing_file.png', 0, 'xMaxYMin meet', '', False),
        ('empty-no-ext', 0, 'xMaxYMin meet', '', False),
        (None, 0, 'xMaxYMin meet', '', False),  # i.e. no theme_frame entry
    ),
)
def test_generate_static_theme_preview(
    convert_svg_to_png_mock,
    write_svg_to_png_mock,
    resize_image_mock,
    pngcrush_image_mock,
    extract_colors_from_image_mock,
    index_addons_mock,
    header_url,
    header_height,
    preserve_aspect_ratio,
    mimetype,
    valid_img,
):
    write_svg_to_png_mock.side_effect = write_empty_png
    convert_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]
    theme_manifest = {
        'images': {},
        'colors': {
            'frame': '#918e43',
            'tab_background_text': '#3deb60',
            'bookmark_text': '#b5ba5b',
            'toolbar_field': '#cc29cc',
            'toolbar_field_text': '#17747d',
            'tab_line': '#00db12',
            'tab_selected': '#40df39',
        },
    }
    if header_url is not None:
        theme_manifest['images']['theme_frame'] = header_url
    addon = addon_factory(
        file_kw={'filename': os.path.join(HEADER_ROOT, 'theme_images.zip')}
    )
    # existing previews should be deleted if they exist
    existing_preview = VersionPreview.objects.create(version=addon.current_version)
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)
    # check that it was deleted
    assert not VersionPreview.objects.filter(id=existing_preview.id).exists()
    assert VersionPreview.objects.filter(version=addon.current_version).count() == 2

    # for svg preview we write the svg twice, 1st with write_svg, later with convert_svg
    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert convert_svg_to_png_mock.call_count == 1
    assert pngcrush_image_mock.call_count == 1

    # First check the firefox Preview is good
    firefox_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['firefox']['position'],
    )
    check_preview(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
    )
    assert write_svg_to_png_mock.call_args_list[0][0][1] == firefox_preview.image_path
    check_thumbnail(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
        firefox_preview.image_path,
        resize_image_mock.call_args_list[0],
        pngcrush_image_mock.call_args_list[0][0],
    )

    # And then Preview used on AMO
    amo_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['amo']['position'],
    )
    check_preview(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
    )
    assert convert_svg_to_png_mock.call_args_list[0][0][0] == amo_preview.image_path
    check_thumbnail(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
        convert_svg_to_png_mock.call_args_list[0][0][1],
        resize_image_mock.call_args_list[1],
    )

    # Now check the svg renders
    firefox_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    interim_amo_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    with open(amo_preview.image_path) as svg:
        amo_svg = svg.read()
    preview_colors = {
        **theme_manifest['colors'],
        'tab_selected toolbar': theme_manifest['colors']['tab_selected'],
    }
    colors = [
        'class="%(field)s %(prop)s" %(prop)s="%(color)s"'
        % {
            'field': key,
            'prop': 'stroke' if key == 'tab_line' else 'fill',
            'color': color,
        }
        for (key, color) in preview_colors.items()
        if key != 'tab_selected'
    ]

    preserve_aspect_ratio = (
        (preserve_aspect_ratio,) * 3
        if not isinstance(preserve_aspect_ratio, tuple)
        else preserve_aspect_ratio
    )
    check_render(
        force_str(firefox_svg),
        header_url,
        header_height,
        preserve_aspect_ratio[0],
        mimetype,
        valid_img,
        colors,
        680,
        92,
        680,
    )
    check_render(
        force_str(interim_amo_svg),
        header_url,
        header_height,
        preserve_aspect_ratio[1],
        mimetype,
        valid_img,
        transparent_colors,
        720,
        92,
        720,
    )
    check_render(
        force_str(amo_svg),
        'empty.jpg',
        92,
        'xMaxYMin slice',
        'image/jpeg',
        True,
        colors,
        720,
        92,
        720,
    )

    index_addons_mock.assert_called_with([addon.id])


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
@mock.patch('olympia.versions.tasks.extract_colors_from_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@mock.patch('olympia.versions.tasks.convert_svg_to_png')
@pytest.mark.parametrize(
    'manifest_images, manifest_colors, svg_colors',
    (
        (  # deprecated properties
            {'headerURL': 'transparent.gif'},
            {
                'accentcolor': '#918e43',  # frame
                'textcolor': '#3deb60',  # tab_background_text
                'toolbar_text': '#b5ba5b',  # bookmark_text
            },
            {
                'frame': '#918e43',
                'tab_background_text': '#3deb60',
                'bookmark_text': '#b5ba5b',
            },
        ),
        (  # defaults and fallbacks
            {'theme_frame': 'transparent.gif'},
            {
                'icons': '#348923',
            },  # icons have class bookmark_text
            {
                'frame': amo.THEME_FRAME_COLOR_DEFAULT,
                'toolbar': 'rgba(255,255,255,0.6)',
                'toolbar_field': 'rgba(255,255,255,1)',
                'tab_selected toolbar': 'rgba(255,255,255,0.6)',
                'tab_line': 'rgba(0,0,0,0.25)',
                'tab_background_text': '',
                'bookmark_text': '#348923',  # icons have class bookmark_text
            },
        ),
        (  # chrome colors
            {'theme_frame': 'transparent.gif'},
            {
                'frame': [123, 45, 67],
                'tab_background_text': [9, 87, 65],
                'bookmark_text': [0, 0, 0],
            },
            {
                'frame': 'rgb(123,45,67)',
                'tab_background_text': 'rgb(9,87,65)',
                'bookmark_text': 'rgb(0,0,0)',
            },
        ),
    ),
)
def test_generate_static_theme_preview_with_alternative_properties(
    convert_svg_to_png_mock,
    write_svg_to_png_mock,
    resize_image_mock,
    pngcrush_image_mock,
    extract_colors_from_image_mock,
    index_addons_mock,
    manifest_images,
    manifest_colors,
    svg_colors,
):
    write_svg_to_png_mock.side_effect = write_empty_png
    convert_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]
    theme_manifest = {
        'images': manifest_images,
        'colors': manifest_colors,
    }
    addon = addon_factory(
        file_kw={'filename': os.path.join(HEADER_ROOT, 'theme_images.zip')}
    )
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)

    # for svg preview we write the svg twice, 1st with write_svg, later with convert_svg
    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert convert_svg_to_png_mock.call_count == 1
    assert pngcrush_image_mock.call_count == 1

    # First check the firefox Preview is good
    firefox_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['firefox']['position'],
    )
    check_preview(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
    )
    assert write_svg_to_png_mock.call_args_list[0][0][1] == firefox_preview.image_path
    check_thumbnail(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
        firefox_preview.image_path,
        resize_image_mock.call_args_list[0],
        pngcrush_image_mock.call_args_list[0][0],
    )

    # And then the Preview used on AMO
    amo_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['amo']['position'],
    )
    check_preview(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
    )
    assert convert_svg_to_png_mock.call_args_list[0][0][0] == amo_preview.image_path
    check_thumbnail(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
        convert_svg_to_png_mock.call_args_list[0][0][1],
        resize_image_mock.call_args_list[1],
    )

    colors = [
        'class="%(field)s %(prop)s" %(prop)s="%(color)s"'
        % {
            'field': key,
            'prop': 'stroke' if key == 'tab_line' else 'fill',
            'color': color,
        }
        for (key, color) in svg_colors.items()
    ]

    firefox_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    interim_amo_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    with open(amo_preview.image_path) as svg:
        amo_svg = svg.read()
    check_render(
        force_str(firefox_svg),
        'transparent.gif',
        1,
        'xMaxYMin meet',
        'image/gif',
        True,
        colors,
        680,
        92,
        680,
    )
    check_render(
        force_str(interim_amo_svg),
        'transparent.gif',
        1,
        'xMaxYMin meet',
        'image/gif',
        True,
        transparent_colors,
        720,
        92,
        720,
    )
    check_render(
        force_str(amo_svg),
        'empty.jpg',
        92,
        'xMaxYMin slice',
        'image/jpeg',
        True,
        colors,
        720,
        92,
        720,
    )


def check_render_additional(svg_content, inner_svg_width, colors):
    # check additional background pattern is correct
    image_width = 270
    image_height = 200
    pattern_x_offset = (inner_svg_width - image_width) // 2
    pattern_tag = (
        '<pattern id="AdditionalBackground1"\n'
        '                   width="%s" height="%s"\n'
        '                   x="%s" y="%s" patternUnits="userSpaceOnUse">'
        % (image_width, image_height, pattern_x_offset, 0)
    )
    assert pattern_tag in svg_content, svg_content
    image_tag = f'<image width="{image_width}" height="{image_height}"'
    assert image_tag in svg_content, svg_content
    rect_tag = (
        '<rect width="100%" height="100%" fill="url(#AdditionalBackground1)"></rect>'
    )
    assert rect_tag in svg_content, svg_content
    # and image content is included and was encoded
    additional = os.path.join(HEADER_ROOT, 'weta_for_tiling.png')
    with root_storage.open(additional, 'rb') as header_file:
        header_blob = header_file.read()
    base_64_uri = 'data:{};base64,{}'.format(
        'image/png',
        force_str(b64encode(header_blob)),
    )
    assert 'xlink:href="%s"></image>' % base_64_uri in svg_content
    # check each of our colors was included
    for color in colors:
        assert color in svg_content


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
@mock.patch('olympia.versions.tasks.extract_colors_from_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@mock.patch('olympia.versions.tasks.convert_svg_to_png')
def test_generate_preview_with_additional_backgrounds(
    convert_svg_to_png_mock,
    write_svg_to_png_mock,
    resize_image_mock,
    pngcrush_image_mock,
    extract_colors_from_image_mock,
    index_addons_mock,
):
    write_svg_to_png_mock.side_effect = write_empty_png
    convert_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]

    theme_manifest = {
        'images': {
            'theme_frame': 'empty.png',
            'additional_backgrounds': ['weta_for_tiling.png'],
        },
        'colors': {
            'textcolor': '#123456',
            # Just textcolor, to test the template defaults and fallbacks.
        },
        'properties': {
            'additional_backgrounds_alignment': ['top'],
            'additional_backgrounds_tiling': ['repeat-x'],
        },
    }
    addon = addon_factory(
        file_kw={
            'filename': os.path.join(
                settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
            )
        }
    )
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)

    # for svg preview we write the svg twice, 1st with write_svg, later with convert_svg
    assert resize_image_mock.call_count == 2
    assert write_svg_to_png_mock.call_count == 2
    assert convert_svg_to_png_mock.call_count == 1
    assert pngcrush_image_mock.call_count == 1

    # First check the firefox Preview is good
    firefox_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['firefox']['position'],
    )
    check_preview(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
    )
    assert write_svg_to_png_mock.call_args_list[0][0][1] == firefox_preview.image_path
    check_thumbnail(
        firefox_preview,
        amo.THEME_PREVIEW_RENDERINGS['firefox'],
        firefox_preview.image_path,
        resize_image_mock.call_args_list[0],
        pngcrush_image_mock.call_args_list[0][0],
    )

    # And then the Preview used on AMO
    amo_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_RENDERINGS['amo']['position'],
    )
    check_preview(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
    )
    assert convert_svg_to_png_mock.call_args_list[0][0][0] == amo_preview.image_path
    check_thumbnail(
        amo_preview,
        amo.THEME_PREVIEW_RENDERINGS['amo'],
        convert_svg_to_png_mock.call_args_list[0][0][1],
        resize_image_mock.call_args_list[1],
    )

    # These defaults are mostly defined in the xml template
    default_colors = (
        ('frame', 'fill', 'rgba(229,230,232,1)'),  # amo.THEME_FRAME_COLOR_DEFAULT
        ('tab_background_text', 'fill', '#123456'),  # the only one defined in manifest
        ('bookmark_text', 'fill', '#123456'),  # should default to tab_background_text
        ('toolbar_field', 'fill', 'rgba(255,255,255,1)'),
        ('toolbar_field_text', 'fill', ''),
        ('tab_line', 'stroke', 'rgba(0,0,0,0.25)'),
        ('tab_selected toolbar', 'fill', 'rgba(255,255,255,0.6)'),
    )
    colors = [
        f'class="{key} {prop}" {prop}="{color}"'
        for (key, prop, color) in default_colors
    ]

    firefox_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    interim_amo_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    with open(amo_preview.image_path) as svg:
        amo_svg = svg.read()
    check_render_additional(force_str(firefox_svg), 680, colors)
    check_render_additional(force_str(interim_amo_svg), 720, transparent_colors)
    check_render(
        force_str(amo_svg),
        'empty.jpg',
        92,
        'xMaxYMin slice',
        'image/jpeg',
        True,
        colors,
        720,
        92,
        720,
    )

    index_addons_mock.assert_called_with([addon.id])


@pytest.mark.django_db
def test_hard_delete_task():
    addon = addon_factory()
    version1 = addon.current_version
    version2 = version_factory(addon=addon)
    assert Version.unfiltered.count() == 2
    hard_delete_versions.delay([version1.pk, version2.pk])
    assert Version.unfiltered.count() == 0


class TestDuplicateAddonVersionForRollback(TestCase):
    def setUp(self):
        create_default_webext_appversion()
        user_factory(id=settings.TASK_USER_ID)
        self.user = user_factory()
        addon = addon_factory(
            name='Rændom add-on',
            guid='@webextension-guid',
            version_kw={
                'version': '0.0.1',
                'created': datetime(2019, 4, 1),
                'min_app_version': '48.0',
                'max_app_version': '*',
                'approval_notes': 'Hey reviewers, this is for you',
                'human_review_date': datetime(2025, 1, 1),
                'release_notes': 'Some notes for 0.0.1',
            },
            file_kw={'filename': 'webextension.xpi'},
            users=[self.user],
        )
        self.rollback_version = addon.current_version
        self.setup_source()

        self.latest_version = version_factory(
            addon=addon, version='0.0.2', human_review_date=datetime(2025, 2, 1)
        )
        assert Version.unfiltered.count() == 2

    def setup_source(self):
        self.source_content = ('foo', 'a' * (2**21))
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr(*self.source_content)
            source_file.seek(0)
            self.rollback_version.source.save(
                os.path.basename(source_file.name), DjangoFile(source_file)
            )
            self.rollback_version.save()
        assert self.rollback_version.source

    def check_activity(self, new):
        al = ActivityLog.objects.get(action=amo.LOG.VERSION_ROLLBACK.id)
        assert set(al.versionlog_set.values_list('version', flat=True)) == {
            new.id,
            self.rollback_version.id,
        }

    def check_compatiblity(self, new):
        assert new.apps.get().min.version == '48.0'
        assert new.apps.get().max.version == '*'

    def check_source(self, new):
        assert new.source
        with zipfile.ZipFile(new.source) as source:
            content = source.read(self.source_content[0])
            assert content == self.source_content[1].encode()

    def check_version_fields(self, new):
        assert new.approval_notes == 'Hey reviewers, this is for you'
        assert new.human_review_date == self.rollback_version.human_review_date
        assert new.release_notes == 'Some new notes for 123'
        self.assertCloseToNow(new.created)

    def check_new_xpi(self, new):
        with zipfile.ZipFile(new.file.file.path) as zipf:
            assert json.loads(zipf.read('manifest.json'))['version'] == new.version

    def check_email(self, new):
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.user.email]
        assert mail.outbox[0].subject == f'Mozilla Add-ons: Rændom add-on {new.version}'
        assert (
            f'Rolling back add-on "{new.addon_id}: Rændom add-on", to version "0.0.1" '
            f'by re-publishing as "{new.version}" successful' in mail.outbox[0].body
        )

    @mock.patch('olympia.versions.tasks.statsd.incr')
    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def _test_rollback_success(self, sign_file_mock, statsd_mock):
        new_version_number = '123'

        duplicate_addon_version_for_rollback.delay(
            version_pk=self.rollback_version.pk,
            new_version_number=new_version_number,
            user_pk=self.user.pk,
            notes={'en-us': f'Some new notes for {new_version_number}'},
        )

        assert self.rollback_version.addon.versions.count() == 3
        new_version = Version.objects.first()
        if self.rollback_version.channel == amo.CHANNEL_LISTED:
            assert self.rollback_version.addon.reload().current_version == new_version
        assert new_version.version == new_version_number
        sign_file_mock.assert_called_once()

        # we log many statsd pings creating a version, this the one we expect
        assert statsd_mock.call_args_list[-2][0] == ('versions.tasks.rollback.success',)

        self.check_activity(new_version)
        self.check_compatiblity(new_version)
        self.check_source(new_version)
        self.check_version_fields(new_version)
        self.check_new_xpi(new_version)
        self.check_email(new_version)
        return new_version

    def test_listed(self):
        new_version = self._test_rollback_success()
        assert not NeedsHumanReview.objects.filter(version=new_version).exists()

    def test_unlisted(self):
        self.rollback_version.update(channel=amo.CHANNEL_UNLISTED)
        new_version = self._test_rollback_success()
        assert new_version.channel == amo.CHANNEL_UNLISTED
        assert not NeedsHumanReview.objects.filter(version=new_version).exists()

    @mock.patch('olympia.versions.tasks.statsd.incr')
    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_missing_file(self, sign_file_mock, statsd_mock):
        new_version_number = '123'
        self.rollback_version.file.update(file='')

        duplicate_addon_version_for_rollback.delay(
            version_pk=self.rollback_version.pk,
            new_version_number=new_version_number,
            user_pk=self.user.pk,
            notes={'en-us': f'Some new notes for {new_version_number}'},
        )

        assert self.rollback_version.addon.versions.count() == 2
        sign_file_mock.assert_not_called()

        assert statsd_mock.call_args_list[0][0] == ('versions.tasks.rollback.failure',)

        al = ActivityLog.objects.get(action=amo.LOG.VERSION_ROLLBACK_FAILED.id)
        assert set(al.versionlog_set.values_list('version', flat=True)) == {
            self.rollback_version.id,
        }
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.user.email]
        assert mail.outbox[0].subject == 'Mozilla Add-ons: Rændom add-on 0.0.1'
        assert (
            f'Rolling back add-on "{self.rollback_version.addon_id}: Rændom add-on", '
            f'to version "0.0.1" failed.' in mail.outbox[0].body
        )

    def test_rollback_from_reviewed_to_unreviewed(self):
        self.rollback_version.update(human_review_date=None)
        new_version = self._test_rollback_success()
        assert new_version.human_review_date is None
        assert NeedsHumanReview.objects.filter(version=new_version).exists()
        assert (
            NeedsHumanReview.objects.filter(version=new_version).get().reason
            == NeedsHumanReview.REASONS.VERSION_ROLLBACK
        )


@pytest.mark.django_db
def test_soft_block_versions():
    developer = user_factory()
    user_factory(pk=settings.TASK_USER_ID)
    # addon with a deleted version that isn't blocked
    addon_with_one_version = addon_factory(
        users=[developer],
        version_kw={'deleted': True},
        file_kw={'status': amo.STATUS_DISABLED},
    )
    # The second version is in an usual state deleted, but the file hasn't been set to
    # disabled. We should silently soft block as normal
    addon_with_two_versions = addon_factory(
        users=[developer], version_kw={'deleted': True}
    )
    version_factory(
        addon=addon_with_two_versions,
        deleted=True,
        file_kw={'status': amo.STATUS_DISABLED},
    )
    partially_blocked_addon = addon_factory(users=[developer])
    existing_block = Block.objects.create(
        guid=partially_blocked_addon.guid, updated_by=user_factory(), reason='something'
    )
    BlockVersion.objects.create(
        block=existing_block, version=partially_blocked_addon.current_version
    )
    other_version_on_partialy_blocked_addon = version_factory(
        addon=partially_blocked_addon, deleted=True
    )

    versions = [
        addon_with_one_version.versions(manager='unfiltered_for_relations').get(),
        addon_with_two_versions.versions(manager='unfiltered_for_relations').all()[0],
        addon_with_two_versions.versions(manager='unfiltered_for_relations').all()[1],
        partially_blocked_addon,
        # should be ignored:
        other_version_on_partialy_blocked_addon,
    ]

    soft_block_versions.delay(version_ids=[ver.id for ver in versions])

    new_blocks = list(Block.objects.exclude(id=existing_block.id))
    assert len(new_blocks) == 2
    assert new_blocks[0].guid == addon_with_two_versions.guid
    assert new_blocks[0].blockversion_set.all()[1].version == versions[1]
    assert new_blocks[0].blockversion_set.all()[0].version == versions[2]
    assert new_blocks[0].reason == 'Version deleted'
    assert new_blocks[1].guid == addon_with_one_version.guid
    assert new_blocks[1].blockversion_set.get().version == versions[0]
    assert new_blocks[0].reason == 'Version deleted'

    assert existing_block.blockversion_set.count() == 2
    assert other_version_on_partialy_blocked_addon.blockversion.block == existing_block
    assert existing_block.reason == 'something'  # not updated

    assert BlockVersion.objects.filter(block_type=BlockType.SOFT_BLOCKED).count() == 4
    assert BlockVersion.objects.filter(block_type=BlockType.BLOCKED).count() == 1

    assert len(mail.outbox) == 0
