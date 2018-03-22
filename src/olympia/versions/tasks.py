import os
import StringIO
import subprocess
import tempfile
from base64 import b64encode
from itertools import izip_longest

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.template import loader

from PIL import Image

import olympia.core.logger
from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.amo.utils import pngcrush_image, resize_image
from olympia.versions.models import VersionPreview


log = olympia.core.logger.getLogger('z.files.utils')


def write_svg_to_png(svg_content, out):
    tmp_args = {'dir': settings.TMP_PATH, 'mode': 'wb', 'suffix': '.svg'}
    with tempfile.NamedTemporaryFile(**tmp_args) as temporary_svg:
        temporary_svg.write(svg_content)
        temporary_svg.flush()

        size = None
        try:
            if not os.path.exists(os.path.dirname(out)):
                os.makedirs(out)
            command = [
                settings.RSVG_CONVERT_BIN,
                '-o', out,
                temporary_svg.name
            ]
            subprocess.check_call(command)
            size = amo.THEME_PREVIEW_SIZE
        except IOError as io_error:
            log.debug(io_error)
        except subprocess.CalledProcessError as process_error:
            log.debug(process_error)
    return size


def encode_header_image(path):
    try:
        with storage.open(path, 'rb') as image:
            header_blob = image.read()
            with Image.open(StringIO.StringIO(header_blob)) as header_image:
                (width, height) = header_image.size
            src = 'data:image/%s;base64,%s' % (
                header_image.format.lower(), b64encode(header_blob))
    except IOError as io_error:
        log.debug(io_error)
        return (None, 0, 0)
    return (src, width, height)


class AdditionalBackground(object):

    @classmethod
    def split_alignment(cls, alignment):
        alignments = alignment.split()
        # e.g. "center top"
        if len(alignments) >= 2:
            return (alignments[0], alignments[1])
        elif len(alignments) == 1:
            # e.g. "left", which is the same as 'left center'
            if alignments[0] in ['left', 'right']:
                return (alignments[0], 'center')
            # e.g. "top", which is the same as 'center top'
            else:
                return ('center', alignments[0])
        else:
            return ('', '')

    def __init__(self, path, alignment, tiling, header_root):
        # If there an unequal number of alignments or tiling to srcs the value
        # will be None so use defaults.
        alignment = (alignment or 'left top').lower()
        tiling = (tiling or 'no-repeat').lower()
        self.src, self.width, self.height = encode_header_image(
            os.path.join(header_root, path))
        self.pattern_width = (self.width if tiling in ['repeat', 'repeat-x']
                              else '100%')
        self.pattern_height = (self.height if tiling in ['repeat', 'repeat-y']
                               else '100%')
        align_x, align_y = self.split_alignment(alignment)
        if align_x == 'right':
            self.pattern_x = amo.THEME_PREVIEW_SIZE.width - self.width
        elif align_x == 'center':
            self.pattern_x = (amo.THEME_PREVIEW_SIZE.width - self.width) / 2
        else:
            self.pattern_x = 0
        if align_y == 'bottom':
            self.pattern_y = amo.THEME_PREVIEW_SIZE.height - self.height
        elif align_y == 'center':
            self.pattern_y = (amo.THEME_PREVIEW_SIZE.height - self.height) / 2
        else:
            self.pattern_y = 0


@task
@write
def generate_static_theme_preview(theme_manifest, header_root, preview):
    tmpl = loader.get_template(
        'devhub/addons/includes/static_theme_preview_svg.xml')
    context = {'amo': amo}
    context.update(theme_manifest.get('colors', {}))
    images_dict = theme_manifest.get('images', {})
    header_url = images_dict.get(
        'headerURL', images_dict.get('theme_frame', ''))

    header_src, header_width, header_height = encode_header_image(
        os.path.join(header_root, header_url))
    meet_or_slice = ('meet' if header_width < amo.THEME_PREVIEW_SIZE.width
                     else 'slice')
    preserve_aspect_ratio = '%s %s' % ('xMaxYMin', meet_or_slice)
    context.update(
        header_src=header_src,
        header_src_height=header_height,
        preserve_aspect_ratio=preserve_aspect_ratio)

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

    svg = tmpl.render(context).encode('utf-8')
    image_size = write_svg_to_png(svg, preview.image_path)
    if image_size:
        pngcrush_image(preview.image_path)
        sizes = {
            # We mimic what resize_preview() does, but in our case, 'image'
            # dimensions are not amo.ADDON_PREVIEW_SIZES[1] but something
            # specific to static themes automatic preview.
            'image': image_size,
            'thumbnail': resize_image(
                preview.image_path, preview.thumbnail_path,
                amo.ADDON_PREVIEW_SIZES[0])[0]
        }
        preview.update(sizes=sizes)


@task
def delete_preview_files(id, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview(id=id))
