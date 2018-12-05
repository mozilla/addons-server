from __future__ import division
import os
from itertools import izip_longest

from django.template import loader

import olympia.core.logger

from olympia import amo
from olympia.addons.tasks import index_addons
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import pngcrush_image
from olympia.devhub.tasks import resize_image
from olympia.files.models import File
from olympia.files.utils import get_background_images
from olympia.versions.models import Version, VersionPreview
from olympia.lib.git import AddonGitRepository

from .utils import (
    AdditionalBackground, process_color_value,
    encode_header, write_svg_to_png)


log = olympia.core.logger.getLogger('z.versions.task')


def _build_static_theme_preview_context(theme_manifest, file_):
    # First build the context shared by both the main preview and the thumb
    context = {'amo': amo}
    context.update(dict(
        process_color_value(prop, color)
        for prop, color in theme_manifest.get('colors', {}).items()))
    images_dict = theme_manifest.get('images', {})
    header_url = images_dict.get(
        'headerURL', images_dict.get('theme_frame', ''))
    file_ext = os.path.splitext(header_url)[1]
    backgrounds = get_background_images(file_, theme_manifest)
    header_src, header_width, header_height = encode_header(
        backgrounds.get(header_url), file_ext)
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
        AdditionalBackground(path, alignment, tiling, backgrounds.get(path))
        for (path, alignment, tiling) in izip_longest(
            additional_srcs, additional_alignments, additional_tiling)
        if path is not None]
    context.update(additional_backgrounds=additional_backgrounds)
    return context


@task
@use_primary_db
def generate_static_theme_preview(theme_manifest, version_pk):
    tmpl = loader.get_template(
        'devhub/addons/includes/static_theme_preview_svg.xml')
    file_ = File.objects.filter(version_id=version_pk).first()
    if not file_:
        return
    context = _build_static_theme_preview_context(theme_manifest, file_)
    sizes = sorted(
        amo.THEME_PREVIEW_SIZES.values(),
        lambda x, y: x['position'] - y['position'])
    for size in sizes:
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
    addon_id = Version.objects.values_list(
        'addon_id', flat=True).get(id=version_pk)
    index_addons.delay([addon_id])


@task
def delete_preview_files(pk, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview.objects.get(pk=pk))


@task
def extract_version_to_git(version_id):
    """Extract a `File` into our git storage backend."""
    version = Version.objects.get(pk=version_id)

    log.info('Extracting {version_id} into git backend'.format(
        version_id=version_id))

    repo = AddonGitRepository.extract_and_commit_from_version(version=version)

    log.info('Extracted {version} into {git_path}'.format(
        version=version_id, git_path=repo.git_repository_path))

    if version.source:
        repo = AddonGitRepository.extract_and_commit_source_from_version(
            version=version)

    log.info('Extracted source files from {version} into {git_path}'.format(
        version=version_id, git_path=repo.git_repository_path))
