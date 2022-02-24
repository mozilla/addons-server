import operator
import os
import itertools
import tempfile
from io import BytesIO

from django.db import transaction
from django.conf import settings
from django.template import loader

from PIL import Image

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import extract_colors_from_image, pngcrush_image, SafeStorage
from olympia.devhub.tasks import resize_image
from olympia.files.models import File
from olympia.files.utils import get_background_images
from olympia.versions.models import Version, VersionPreview

from .utils import (
    AdditionalBackground,
    convert_svg_to_png,
    encode_header,
    process_color_value,
    write_svg_to_png,
)


log = olympia.core.logger.getLogger('z.versions.task')


def _build_static_theme_preview_context(theme_manifest, file_):
    # First build the context shared by both the main preview and the thumb
    context = {'amo': amo}
    context.update(
        dict(
            process_color_value(prop, color)
            for prop, color in theme_manifest.get('colors', {}).items()
        )
    )
    images_dict = theme_manifest.get('images', {})
    header_url = images_dict.get('theme_frame', images_dict.get('headerURL', ''))
    file_ext = os.path.splitext(header_url)[1]
    backgrounds = get_background_images(file_, theme_manifest)
    header_src, header_width, header_height = encode_header(
        backgrounds.get(header_url), file_ext
    )
    context.update(
        header_src=header_src,
        header_src_height=header_height,
        header_width=header_width,
    )
    # Limit the srcs rendered to 15 to ameliorate DOSing somewhat.
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1435191 for background.
    additional_srcs = images_dict.get('additional_backgrounds', [])[:15]
    additional_alignments = theme_manifest.get('properties', {}).get(
        'additional_backgrounds_alignment', []
    )
    additional_tiling = theme_manifest.get('properties', {}).get(
        'additional_backgrounds_tiling', []
    )
    additional_backgrounds = [
        AdditionalBackground(path, alignment, tiling, backgrounds.get(path))
        for (path, alignment, tiling) in itertools.zip_longest(
            additional_srcs, additional_alignments, additional_tiling
        )
        if path is not None
    ]
    context.update(additional_backgrounds=additional_backgrounds)
    return context


UI_FIELDS = (
    'toolbar',
    'tab_selected',
    'tab_line',
    'bookmark_text',
    'tab_background_text',
    'toolbar_field',
    'toolbar_field_text',
    'icons',
)
TRANSPARENT_UI = {field: 'rgb(0,0,0,0)' for field in UI_FIELDS}


def render_to_svg(template, context, preview, thumbnail_dimensions, theme_manifest):
    tmp_args = {
        'dir': settings.TMP_PATH,
        'mode': 'wb',
        'delete': not settings.DEBUG,
        'suffix': '.png',
    }

    # first stage - just the images
    image_only_svg = template.render(context).encode('utf-8')

    with BytesIO() as background_blob:
        # write the image only background to a file and back to a blob
        with tempfile.NamedTemporaryFile(**tmp_args) as background_png:
            if not write_svg_to_png(image_only_svg, background_png.name):
                return
            # TODO: improvement - only re-encode jpg backgrounds as jpg?
            Image.open(background_png.name).convert('RGB').save(
                background_blob, 'JPEG', quality=80
            )

        # and encode the image in base64 to use in the context
        try:
            header_src, _, _ = encode_header(background_blob.getvalue(), 'jpg')
        except Exception as exc:
            log.info('Exception during svg preview generation %s', exc)
            return

    # then rebuild a context with it and render
    with_ui_context = {
        **dict(
            process_color_value(prop, color)
            for prop, color in theme_manifest.get('colors', {}).items()
        ),
        'amo': amo,
        'header_src': header_src,
        'svg_render_size': context['svg_render_size'],
        'header_src_height': context['svg_render_size'].height,
        'header_width': context['svg_render_size'].width,
    }
    finished_svg = template.render(with_ui_context).encode('utf-8')

    # and write that svg to preview.image_path
    storage = SafeStorage(user_media=VersionPreview.media_folder)
    with storage.open(preview.image_path, 'wb') as image_path:
        image_path.write(finished_svg)

    # then also write a fully rendered svg and resize for the thumbnails
    with tempfile.NamedTemporaryFile(**tmp_args) as complete_preview_as_png:
        if convert_svg_to_png(preview.image_path, complete_preview_as_png.name):
            resize_image(
                complete_preview_as_png.name,
                preview.thumbnail_path,
                thumbnail_dimensions,
                format=preview.get_format('thumbnail'),
                quality=35,  # It's ignored for png format, so it's fine to always set.
            )
            return True


def render_to_png(template, context, preview, thumbnail_dimensions):
    svg = template.render(context).encode('utf-8')
    if write_svg_to_png(svg, preview.image_path):
        resize_image(
            preview.image_path,
            preview.thumbnail_path,
            thumbnail_dimensions,
            format=preview.get_format('thumbnail'),
            quality=35,  # It's ignored for png format, so it's fine to always set.
        )
        pngcrush_image(preview.image_path)
        return True


@task
@use_primary_db
def generate_static_theme_preview(theme_manifest, version_pk):
    # Make sure we import `index_addons` late in the game to avoid having
    # a "copy" of it here that won't get mocked by our ESTestCase
    from olympia.addons.tasks import index_addons

    tmpl = loader.get_template('devhub/addons/includes/static_theme_preview_svg.xml')
    file_ = File.objects.filter(version_id=version_pk).first()
    if not file_:
        return
    complete_context = _build_static_theme_preview_context(theme_manifest, file_)
    renderings = sorted(
        amo.THEME_PREVIEW_RENDERINGS.values(), key=operator.itemgetter('position')
    )
    colors = None
    old_preview_ids = list(
        VersionPreview.objects.filter(version_id=version_pk).values_list(
            'id', flat=True
        )
    )
    for rendering in renderings:
        # Create a Preview for this rendering.
        preview = VersionPreview.objects.create(
            version_id=version_pk,
            position=rendering['position'],
            sizes={
                'image_format': rendering['image_format'],
                'thumbnail_format': rendering['thumbnail_format'],
            },
        )

        # Add the size to the context and render
        complete_context.update(svg_render_size=rendering['full'])
        if rendering['image_format'] == 'svg':
            render_success = render_to_svg(
                tmpl,
                {**complete_context, **TRANSPARENT_UI},
                preview,
                rendering['thumbnail'],
                theme_manifest,
            )
        else:
            render_success = render_to_png(
                tmpl, complete_context, preview, rendering['thumbnail']
            )
        if render_success:
            # Extract colors once and store it for all previews.
            # Use the thumbnail for extra speed, we don't need to be super accurate.
            if colors is None:
                colors = extract_colors_from_image(preview.thumbnail_path)
            data = {
                'sizes': {
                    'image': rendering['full'],
                    'thumbnail': rendering['thumbnail'],
                    'image_format': rendering['image_format'],
                    'thumbnail_format': rendering['thumbnail_format'],
                },
                'colors': colors,
            }
            preview.update(**data)
    VersionPreview.objects.filter(id__in=old_preview_ids).delete()
    addon_id = Version.objects.values_list('addon_id', flat=True).get(id=version_pk)
    index_addons.delay([addon_id])


@task
def delete_preview_files(pk, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview.objects.get(pk=pk)
    )


@task
@use_primary_db
def delete_list_theme_previews(addon_ids, **kw):
    # Make sure we import `index_addons` late in the game to avoid having
    # a "copy" of it here that won't get mocked by our ESTestCase
    from olympia.addons.tasks import index_addons

    log.info(
        '[%s@%s] Deleting preview sizes for themes starting at id: %s...'
        % (len(addon_ids), delete_list_theme_previews.rate_limit, addon_ids[0])
    )
    for addon_id in addon_ids:
        log.info('Deleting "list" size previews for theme: %s' % addon_id)
        VersionPreview.objects.filter(
            version__addon_id=addon_id, sizes__image=[760, 92]
        ).delete()

    index_addons.delay(addon_ids)


@task
@use_primary_db
def hard_delete_versions(version_ids, **kw):
    """Hard delete the given versions by id."""
    log.info(
        '[%s@%s] Hard deleting versions starting at id: %s...'
        % (
            len(version_ids),
            hard_delete_versions.rate_limit,
            version_ids[0],
        )
    )
    versions = Version.unfiltered.filter(pk__in=version_ids).no_transforms()
    for version in versions:
        with transaction.atomic():
            version.delete(hard=True)
