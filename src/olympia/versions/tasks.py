from __future__ import division
import os
from itertools import izip_longest

from django.template import loader

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.amo.utils import pngcrush_image
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
@write
def generate_static_theme_preview(theme_manifest, header_root, preview):
    def calc_aspect_ratio(svg_size, header_width):
        meet_or_slice = 'meet' if header_width < svg_size.width else 'slice'
        return '%s %s' % ('xMaxYMin', meet_or_slice)

    FULL_PREVIEW = amo.THEME_PREVIEW_SIZES['full']
    LIST_PREVIEW = amo.THEME_PREVIEW_SIZES['thumb']

    tmpl = loader.get_template(
        'devhub/addons/includes/static_theme_preview_svg.xml')

    context = _build_static_theme_preview_context(theme_manifest, header_root)

    # Then add the size specific stuff
    context.update(
        svg_size=FULL_PREVIEW,
        preserve_aspect_ratio=calc_aspect_ratio(
            FULL_PREVIEW, context['header_width']))
    for background in context['additional_backgrounds']:
        background.calculate_pattern_offsets(context['svg_size'])
    # Aaand render
    svg = tmpl.render(context).encode('utf-8')
    preview_sizes = {}
    if write_svg_to_png(svg, preview.image_path):
        pngcrush_image(preview.image_path)
        preview_sizes['image'] = FULL_PREVIEW

    # Then reuse the existing context and update size calculations
    scaling_needed = LIST_PREVIEW.height / FULL_PREVIEW.height
    inner_svg_size = LIST_PREVIEW._make(
        (LIST_PREVIEW.width / scaling_needed, FULL_PREVIEW.height))
    context.update(
        svg_size=LIST_PREVIEW,
        svg_scale=scaling_needed,
        svg_inner_width=inner_svg_size.width,
        svg_inner_height=inner_svg_size.height,
        preserve_aspect_ratio=calc_aspect_ratio(
            inner_svg_size, context['header_width']))
    for background in context['additional_backgrounds']:
        background.calculate_pattern_offsets(inner_svg_size)
    # Then re-render
    svg = tmpl.render(context).encode('utf-8')
    if write_svg_to_png(svg, preview.thumbnail_path):
        pngcrush_image(preview.thumbnail_path)
        preview_sizes['thumbnail'] = LIST_PREVIEW

    if preview_sizes:
        preview.update(sizes=preview_sizes)


@task
def delete_preview_files(id, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview(id=id))
