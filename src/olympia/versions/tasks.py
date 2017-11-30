import os
from base64 import b64encode

from django.core.files.storage import default_storage as storage
from django.template import loader

from wand.image import Image as WandImage

import olympia.core.logger
from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import write


log = olympia.core.logger.getLogger('z.files.utils')


def write_svg_to_png(svg_content, out):
    temp_svg_path = out + '.svg'
    size = None
    try:
        with storage.open(temp_svg_path, 'wb') as svgout:
            svgout.write(svg_content)
        with storage.open(temp_svg_path, 'rb') as svgout:
            with WandImage(file=svgout, format='svg') as img:
                img.format = 'png'
                with storage.open(out, 'wb') as out:
                    img.save(file=out)
                    size = img.size
    except IOError as ioerror:
        log.debug(ioerror)
    finally:
        if os.path.exists(temp_svg_path):
            os.unlink(temp_svg_path)
    return size


@task
@write
def generate_static_theme_preview(theme_manifest, header_root, preview):
    tmpl = loader.get_template(
        'devhub/addons/includes/static_theme_preview_svg.xml')
    context = {'amo': amo}
    context.update(theme_manifest.get('colors', {}))
    header_url = theme_manifest.get('images', {}).get('headerURL')

    header_path = os.path.join(header_root, header_url)
    try:
        with storage.open(header_path, 'rb') as header_file:
            header_blob = header_file.read()
            with WandImage(blob=header_blob) as header_image:
                (width, height) = header_image.size
                context.update(header_src_height=height)
                meetOrSlice = ('meet' if width < amo.THEME_PREVIEW_SIZE.width
                               else 'slice')
                context.update(
                    preserve_aspect_ratio='xMaxYMin %s' % meetOrSlice)
                data_url = 'data:%s;base64,%s' % (
                    header_image.mimetype, b64encode(header_blob))
                context.update(header_src=data_url)
    except IOError as ioerror:
        log.debug(ioerror)

    svg = tmpl.render(context).encode('utf-8')
    size = write_svg_to_png(svg, preview.image_path)
    if size:
        preview.update(sizes={'image': size})
