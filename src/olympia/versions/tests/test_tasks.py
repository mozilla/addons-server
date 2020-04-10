import os
import zipfile
from base64 import b64encode
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files import temp
from django.utils.encoding import force_text

from unittest import mock
import pytest

from olympia import amo
from olympia.addons.models import GitExtraction
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import addon_factory, version_factory
from olympia.addons.cron import hide_disabled_files
from olympia.files.utils import id_to_path
from olympia.versions.models import VersionPreview
from olympia.versions.tasks import (
    generate_static_theme_preview, extract_addon_to_git,
    extract_version_to_git, extract_version_source_to_git)
from olympia.lib.git import AddonGitRepository, BrokenRefError


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
                mimetype, force_text(b64encode(header_blob)))
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
    assert preview_instance.colors


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
@mock.patch('olympia.versions.tasks.extract_colors_from_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@pytest.mark.parametrize(
    'header_url, header_height, preserve_aspect_ratio, mimetype, valid_img', (
        ('transparent.gif', 1, 'xMaxYMin meet', 'image/gif', True),
        ('weta.png', 200, 'xMaxYMin meet', 'image/png', True),
        ('wetalong.png', 200, 'xMaxYMin slice', 'image/png', True),
        ('weta_theme_full.svg', 92,  # different value for 680 and 760/720
         ('xMaxYMin slice', 'xMaxYMin meet', 'xMaxYMin meet'),
         'image/svg+xml', True),
        ('transparent.svg', 1, 'xMaxYMin meet', 'image/svg+xml', True),
        ('missing_file.png', 0, 'xMaxYMin meet', '', False),
        ('empty-no-ext', 0, 'xMaxYMin meet', '', False),
        (None, 0, 'xMaxYMin meet', '', False),  # i.e. no theme_frame entry
    )
)
def test_generate_static_theme_preview(
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock,
        extract_colors_from_image_mock, index_addons_mock,
        header_url, header_height, preserve_aspect_ratio, mimetype, valid_img):
    write_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]
    theme_manifest = {
        "images": {
        },
        "colors": {
            "frame": "#918e43",
            "tab_background_text": "#3deb60",
            "bookmark_text": "#b5ba5b",
            "toolbar_field": "#cc29cc",
            "toolbar_field_text": "#17747d",
            "tab_line": "#00db12",
            "tab_selected": "#40df39",
        }
    }
    if header_url is not None:
        theme_manifest['images']['theme_frame'] = header_url
    addon = addon_factory()
    destination = addon.current_version.all_files[0].current_file_path
    zip_file = os.path.join(HEADER_ROOT, 'theme_images.zip')
    copy_stored_file(zip_file, destination)
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)

    assert resize_image_mock.call_count == 3
    assert write_svg_to_png_mock.call_count == 3
    assert pngcrush_image_mock.call_count == 3

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

    # And finally the new single Preview
    single_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['single']['position'])
    check_preview(
        single_preview, amo.THEME_PREVIEW_SIZES['single'],
        write_svg_to_png_mock.call_args_list[2][0],
        resize_image_mock.call_args_list[2][0],
        pngcrush_image_mock.call_args_list[2][0])

    # Now check the svg renders
    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    single_svg = write_svg_to_png_mock.call_args_list[2][0][0]
    colors = ['class="%s" fill="%s"' % (key, color)
              for (key, color) in theme_manifest['colors'].items()]
    preserve_aspect_ratio = (
        (preserve_aspect_ratio, ) * 3
        if not isinstance(preserve_aspect_ratio, tuple)
        else preserve_aspect_ratio)
    check_render(force_text(header_svg), header_url, header_height,
                 preserve_aspect_ratio[0], mimetype, valid_img, colors,
                 680, 92, 680)
    check_render(force_text(list_svg), header_url, header_height,
                 preserve_aspect_ratio[1], mimetype, valid_img, colors,
                 760, 92, 760)
    check_render(force_text(single_svg), header_url, header_height,
                 preserve_aspect_ratio[2], mimetype, valid_img, colors,
                 720, 92, 720)

    index_addons_mock.assert_called_with([addon.id])


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
@mock.patch('olympia.versions.tasks.extract_colors_from_image')
@mock.patch('olympia.versions.tasks.pngcrush_image')
@mock.patch('olympia.versions.tasks.resize_image')
@mock.patch('olympia.versions.tasks.write_svg_to_png')
@pytest.mark.parametrize(
    'manifest_images, manifest_colors, svg_colors', (
        (  # deprecated properties
            {"headerURL": "transparent.gif"},
            {
                "accentcolor": "#918e43",  # frame
                "textcolor": "#3deb60",  # tab_background_text
                "toolbar_text": "#b5ba5b",  # bookmark_text
            },
            {
                "frame": "#918e43",
                "tab_background_text": "#3deb60",
                "bookmark_text": "#b5ba5b",
            }
        ),
        (  # defaults and fallbacks
            {"theme_frame": "transparent.gif"},
            {
                "icons": "#348923",  # icons have class bookmark_text
            },
            {
                "frame": amo.THEME_FRAME_COLOR_DEFAULT,
                "toolbar": "rgba(255,255,255,0.6)",
                "toolbar_field": "rgba(255,255,255,1)",
                "tab_selected": "rgba(0,0,0,0)",
                "tab_line": "rgba(0,0,0,0.25)",
                "tab_background_text": "",
                "bookmark_text": "#348923",  # icons have class bookmark_text
            },
        ),
        (  # chrome colors
            {"theme_frame": "transparent.gif"},
            {
                "frame": [123, 45, 67],
                "tab_background_text": [9, 87, 65],
                "bookmark_text": [0, 0, 0],
            },
            {
                "frame": "rgb(123,45,67)",
                "tab_background_text": "rgb(9,87,65)",
                "bookmark_text": "rgb(0,0,0)",
            },
        ),
    )
)
def test_generate_static_theme_preview_with_alternative_properties(
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock,
        extract_colors_from_image_mock, index_addons_mock,
        manifest_images, manifest_colors, svg_colors):
    write_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]
    theme_manifest = {
        "images": manifest_images,
        "colors": manifest_colors,
    }
    addon = addon_factory()
    destination = addon.current_version.all_files[0].current_file_path
    zip_file = os.path.join(HEADER_ROOT, 'theme_images.zip')
    copy_stored_file(zip_file, destination)
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)

    assert resize_image_mock.call_count == 3
    assert write_svg_to_png_mock.call_count == 3
    assert pngcrush_image_mock.call_count == 3

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

    # And finally the new single Preview
    single_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['single']['position'])
    check_preview(
        single_preview, amo.THEME_PREVIEW_SIZES['single'],
        write_svg_to_png_mock.call_args_list[2][0],
        resize_image_mock.call_args_list[2][0],
        pngcrush_image_mock.call_args_list[2][0])

    colors = ['class="%s" fill="%s"' % (key, color)
              for (key, color) in svg_colors.items()]

    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    single_svg = write_svg_to_png_mock.call_args_list[2][0][0]
    check_render(force_text(header_svg), 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 680, 92, 680)
    check_render(force_text(list_svg), 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 760, 92, 760)
    check_render(force_text(single_svg), 'transparent.gif', 1,
                 'xMaxYMin meet', 'image/gif', True, colors, 720, 92, 720)


def check_render_additional(svg_content, inner_svg_width, colors):
    # check additional background pattern is correct
    image_width = 270
    image_height = 200
    pattern_x_offset = (inner_svg_width - image_width) // 2
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
    base_64_uri = 'data:%s;base64,%s' % (
        'image/png', force_text(b64encode(header_blob)))
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
def test_generate_preview_with_additional_backgrounds(
        write_svg_to_png_mock, resize_image_mock, pngcrush_image_mock,
        extract_colors_from_image_mock, index_addons_mock):
    write_svg_to_png_mock.return_value = True
    extract_colors_from_image_mock.return_value = [
        {'h': 9, 's': 8, 'l': 7, 'ratio': 0.6}
    ]

    theme_manifest = {
        "images": {
            "theme_frame": "empty.png",
            "additional_backgrounds": ["weta_for_tiling.png"],
        },
        "colors": {
            "textcolor": "#123456",
            # Just textcolor, to test the template defaults and fallbacks.
        },
        "properties": {
            "additional_backgrounds_alignment": ["top"],
            "additional_backgrounds_tiling": ["repeat-x"],
        },
    }
    addon = addon_factory()
    destination = addon.current_version.all_files[0].current_file_path
    zip_file = os.path.join(
        settings.ROOT,
        'src/olympia/devhub/tests/addons/static_theme_tiled.zip')
    copy_stored_file(zip_file, destination)
    generate_static_theme_preview(theme_manifest, addon.current_version.pk)

    assert resize_image_mock.call_count == 3
    assert write_svg_to_png_mock.call_count == 3
    assert pngcrush_image_mock.call_count == 3

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

    # And finally the new single Preview
    single_preview = VersionPreview.objects.get(
        version=addon.current_version,
        position=amo.THEME_PREVIEW_SIZES['single']['position'])
    check_preview(
        single_preview, amo.THEME_PREVIEW_SIZES['single'],
        write_svg_to_png_mock.call_args_list[2][0],
        resize_image_mock.call_args_list[2][0],
        pngcrush_image_mock.call_args_list[2][0])

    # These defaults are mostly defined in the xml template
    default_colors = {
        "frame": "rgba(229,230,232,1)",  # amo.THEME_FRAME_COLOR_DEFAULT
        "tab_background_text": "#123456",  # the only one defined in 'manifest'
        "bookmark_text": "#123456",  # should default to tab_background_text
        "toolbar_field": "rgba(255,255,255,1)",
        "toolbar_field_text": "",
        "tab_line": "rgba(0,0,0,0.25)",
        "tab_selected": "rgba(0,0,0,0)",
    }
    colors = ['class="%s" fill="%s"' % (key, color)
              for (key, color) in default_colors.items()]

    header_svg = write_svg_to_png_mock.call_args_list[0][0][0]
    list_svg = write_svg_to_png_mock.call_args_list[1][0][0]
    single_svg = write_svg_to_png_mock.call_args_list[2][0][0]
    check_render_additional(force_text(header_svg), 680, colors)
    check_render_additional(force_text(list_svg), 760, colors)
    check_render_additional(force_text(single_svg), 720, colors)

    index_addons_mock.assert_called_with([addon.id])


@pytest.mark.django_db
def test_extract_version_to_git():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    extract_version_to_git(addon.current_version.pk)

    repo = AddonGitRepository(addon.pk)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'addon')
    assert os.listdir(repo.git_repository_path) == ['.git']


@pytest.mark.django_db
def test_extract_version_to_git_stops_on_broken_ref():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    repo = AddonGitRepository(addon.pk)
    # Force the creation of the git repository.
    repo.git_repository
    assert repo.is_extracted
    # Create a broken ref, see:
    # https://github.com/mozilla/addons-server/issues/13590
    Path(f'{repo.git_repository_path}/.git/refs/heads/listed').touch()

    with pytest.raises(BrokenRefError):
        extract_version_to_git(
            addon.current_version.pk,
            stop_on_broken_ref=True,
        )


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_addon_to_git.delay')
def test_extract_version_to_git_with_broken_reference(
        extract_addon_to_git_mock):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    repo = AddonGitRepository(addon.pk)
    # Extract the current version once so that it has a git hash.
    extract_version_to_git(addon.current_version.pk)
    addon.current_version.refresh_from_db()
    assert addon.current_version.git_hash
    assert repo.is_extracted
    # Emptying this file will break the git reference to the 'listed' branch.
    Path(f'{repo.git_repository_path}/.git/refs/heads/listed').write_text('')

    # Extract again. It does not really matter that we pass the same version
    # because retrieving the branch will fail before we commit anything.
    extract_version_to_git(addon.current_version.pk)
    addon.current_version.refresh_from_db()

    # When we detect a broken git reference, we reset the git hash of each
    # version...
    assert not addon.current_version.git_hash
    # ...then delete the repository...
    assert not repo.is_extracted
    # ...and we create a new task to re-extract the add-on.
    extract_addon_to_git_mock.assert_called_with(addon.id)


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git.apply_async')
def test_extract_version_to_git_can_be_delayed(
    extract_version_to_git_mock
):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    repo = AddonGitRepository(addon.pk)
    # Lock the add-on for git extraction.
    GitExtraction.objects.create(addon=addon, in_progress=True)
    note = 'some note'
    author_id = 123

    extract_version_to_git(
        addon.current_version.pk,
        author_id=author_id,
        note=note,
    )

    assert not repo.is_extracted
    extract_version_to_git_mock.assert_called_with(
        kwargs={
            'version_id': addon.current_version.pk,
            'author_id': author_id,
            'note': note,
            'stop_on_broken_ref': False,
        },
        countdown=30,
    )


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git.apply_async')
def test_extract_version_to_git_cannot_be_delayed(
    extract_version_to_git_mock
):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    repo = AddonGitRepository(addon.pk)
    # Lock the add-on for git extraction.
    GitExtraction.objects.create(addon=addon, in_progress=True)

    extract_version_to_git(addon.current_version.pk, can_be_delayed=False)

    assert repo.is_extracted
    extract_version_to_git_mock.assert_not_called()


@pytest.mark.django_db
def test_extract_version_to_git_deleted_version():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    version = addon.current_version
    version.delete()

    hide_disabled_files()

    extract_version_to_git(version.pk)

    repo = AddonGitRepository(addon.pk)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'addon')
    assert os.listdir(repo.git_repository_path) == ['.git']


@pytest.mark.django_db
def test_extract_version_source_to_git():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    # Generate source file
    source = temp.NamedTemporaryFile(suffix='.zip', dir=settings.TMP_PATH)
    with zipfile.ZipFile(source, 'w') as zip_file:
        zip_file.writestr('manifest.json', '{}')
    source.seek(0)

    addon.current_version.update(source=source)

    extract_version_source_to_git(addon.current_version.pk)

    repo = AddonGitRepository(addon.pk, package_type='source')

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'source')
    assert os.listdir(repo.git_repository_path) == ['.git']


@pytest.mark.django_db
def test_extract_version_source_to_git_deleted_version():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    version = addon.current_version
    version.delete()

    hide_disabled_files()

    # Generate source file
    source = temp.NamedTemporaryFile(suffix='.zip', dir=settings.TMP_PATH)
    with zipfile.ZipFile(source, 'w') as zip_file:
        zip_file.writestr('manifest.json', '{}')
    source.seek(0)
    version.update(source=source)

    extract_version_source_to_git(version.pk)

    repo = AddonGitRepository(addon.pk, package_type='source')

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'source')
    assert os.listdir(repo.git_repository_path) == ['.git']


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git')
def test_extract_addon_to_git(extract_version_to_git_mock):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    # A brand new add-on does not have an associated GitExtraction model.
    assert not hasattr(addon, 'gitextraction')

    extract_addon_to_git(addon.pk)
    addon.refresh_from_db()

    extract_version_to_git_mock.assert_called_with(
        addon.current_version.pk,
        stop_on_broken_ref=True,
        can_be_delayed=False,
    )
    # A GitExtraction object should have been created.
    assert hasattr(addon, 'gitextraction')
    # The add-on should not be locked anymore.
    assert not addon.git_extraction_is_in_progress


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git')
def test_extract_addon_to_git_with_gitextraction(extract_version_to_git_mock):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    # Create a GitExtraction object. It should be reused by the task.
    GitExtraction.objects.create(addon=addon)

    extract_addon_to_git(addon.pk)
    addon.refresh_from_db()

    extract_version_to_git_mock.assert_called_with(
        addon.current_version.pk,
        stop_on_broken_ref=True,
        can_be_delayed=False,
    )
    # The add-on should not be locked anymore.
    assert not addon.git_extraction_is_in_progress


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git')
def test_extract_addon_to_git_returns_when_locked(extract_version_to_git_mock):
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    # Lock the add-on for git extraction.
    GitExtraction.objects.create(addon=addon, in_progress=True)

    extract_addon_to_git(addon.pk)

    extract_version_to_git_mock.assert_not_called()


@pytest.mark.django_db
@mock.patch('olympia.versions.tasks.extract_version_to_git')
def test_extract_addon_to_git_multiple_versions(extract_version_to_git_mock):
    file_kw = {'filename': 'webextension_no_id.xpi'}
    addon = addon_factory(file_kw=file_kw)
    version_factory(addon=addon, file_kw=file_kw)
    version_factory(addon=addon, file_kw=file_kw, deleted=True)
    versions = addon.versions(manager='unfiltered_for_relations').order_by(
        'created'
    )
    assert len(versions) == 3

    extract_addon_to_git(addon.pk)
    addon.refresh_from_db()

    expected_calls = [
        mock.call(
            versions[0].pk, stop_on_broken_ref=True, can_be_delayed=False
        ),
        mock.call(
            versions[1].pk, stop_on_broken_ref=True, can_be_delayed=False
        ),
        mock.call(
            versions[2].pk, stop_on_broken_ref=True, can_be_delayed=False
        ),
    ]
    extract_version_to_git_mock.assert_has_calls(expected_calls)
    assert extract_version_to_git_mock.call_count == len(expected_calls)
    # The add-on should not be locked anymore.
    assert not addon.git_extraction_is_in_progress
