from __future__ import division
import os
from itertools import izip_longest

from django.template import loader

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import pngcrush_image
from olympia.devhub.tasks import resize_image
from olympia.versions.models import VersionPreview

from .utils import (
    AdditionalBackground, process_color_value,
    encode_header_image, write_svg_to_png)


def _build_static_theme_preview_context(theme_manifest, header_root):
    # First build the context shared by both the main preview and the thumb
    context = {'amo': amo}
    context.update(
        {process_color_value(prop, color)
         for prop, color in theme_manifest.get('colors', {}).items()})
    images_dict = theme_manifest.get('images', {})
    header_url = images_dict.get(
        'headerURL', images_dict.get('theme_frame', ''))
    header_src, header_width, header_height = encode_header_image(
        os.path.join(header_root, header_url))
    context.update(
        header_src=header_src,
        header_src_height=header_height,
        header_width=header_width)
    # Limit the srcs rendered to 15 to ameliorate DOSing somewhat.
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1435191 for background.
    additional_srcs = images_dict.get('additional_backgrounds', [])[:15]
    additional_alignments = (theme_manifest.get('properties', {})
                             .get('additional_backgrounds_alignment', []))
    additional_tiling = (theme_manifest.get('properties', {})
                         .get('additional_backgrounds_tiling', []))
    additional_backgrounds = [
        AdditionalBackground(path, alignment, tiling, header_root)
        for (path, alignment, tiling) in izip_longest(
            additional_srcs, additional_alignments, additional_tiling)
        if path is not None]
    context.update(additional_backgrounds=additional_backgrounds)
    return context


@task
@use_primary_db
def generate_static_theme_preview(theme_manifest, header_root, version_pk):
    tmpl = loader.get_template(
        'devhub/addons/includes/static_theme_preview_svg.xml')
    context = _build_static_theme_preview_context(theme_manifest, header_root)
    for size in sorted(amo.THEME_PREVIEW_SIZES.values()):
        # Create a Preview for this size.
        preview = VersionPreview.objects.create(
            version_id=version_pk, position=size['position'])
        # Add the size to the context and render
        context.update(svg_render_size=size['full'])
        svg = tmpl.render(context).encode('utf-8')
        if write_svg_to_png(svg, preview.image_path):
            resize_image(
                preview.image_path, preview.thumbnail_path, size['thumbnail'])
            pngcrush_image(preview.image_path)
            preview_sizes = {}
            preview_sizes['image'] = size['full']
            preview_sizes['thumbnail'] = size['thumbnail']
            preview.update(sizes=preview_sizes)


@task
def delete_preview_files(pk, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview.objects.get(pk=pk))
