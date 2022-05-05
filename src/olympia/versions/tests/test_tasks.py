import os
from base64 import b64encode

from django.conf import settings
from django.utils.encoding import force_str

from unittest import mock
import pytest

from olympia import amo
from olympia.amo.tests import addon_factory, root_storage, version_factory
from olympia.versions.models import Version, VersionPreview
from olympia.versions.tasks import (
    generate_static_theme_preview,
    hard_delete_versions,
    UI_FIELDS,
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
    addon = addon_factory()
    destination = addon.current_version.file.file_path
    zip_file = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
    )
    root_storage.copy_stored_file(zip_file, destination)
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
