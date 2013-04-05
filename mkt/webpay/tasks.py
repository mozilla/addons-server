from datetime import datetime, timedelta
import logging
import os
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction

from celeryutils import task
import requests

from amo.utils import ImageCheck, resize_image

from .models import ProductIcon

log = logging.getLogger('z.webpay.tasks')


@task
@transaction.commit_on_success
def fetch_product_icon(url, ext_size, size, read_size=100000, **kw):
    """
    Fetch and store a webpay product icon.

    Parameters:

    **url**
        Absolute URL of icon
    **ext_size**
        The height/width size that the developer claims it to be
    **size**
        The height/width webpay wants us to resize it to

    The icon will be resized if its ext_size is larger than size.
    See webpay for details on how this is used for in-app payments.
    """
    if ext_size > size:
        resize = True
    else:
        # Do not resize the icon. Adjust size so that it is correct.
        resize = False
        size = ext_size
    try:
        cached_im = ProductIcon.objects.get(ext_url=url, ext_size=ext_size)
    except ProductIcon.DoesNotExist:
        cached_im = None

    now = datetime.now()
    if cached_im and (cached_im.modified >
                      now - timedelta(days=settings.PRODUCT_ICON_EXPIRY)):
        log.info('Already fetched URL recently: %s' % url)
        return

    tmp_dest = tempfile.NamedTemporaryFile(delete=False)
    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        for chunk in res.iter_content(read_size):
            tmp_dest.write(chunk)
    except (AttributeError, AssertionError):
        raise  # Raise test-related exceptions.
    except:
        tmp_dest.close()
        os.unlink(tmp_dest.name)
        log.error('fetch_product_icon error with %s' % url, exc_info=True)
        return
    else:
        tmp_dest.close()

    try:
        valid, img_format = _check_image(tmp_dest.name, url)
        if valid:
            if resize:
                log.info('resizing in-app image for URL %s' % url)
                tmp_dest = _resize_image(tmp_dest, size)

            # Save the image to the db.
            attr = dict(ext_size=ext_size, size=size, ext_url=url,
                        format=img_format)
            if cached_im:
                cached_im.update(**attr)
            else:
                cached_im = ProductIcon.objects.create(**attr)
            log.info('saving image from URL %s' % url)
            _store_image(tmp_dest, cached_im, read_size)
    finally:
        os.unlink(tmp_dest.name)


def _check_image(im_path, abs_url):
    valid = True
    img_format = ''
    with open(im_path, 'rb') as fp:
        im = ImageCheck(fp)
        if not im.is_image():
            valid = False
            log.error('image at %s is not an image' % abs_url)
        if im.is_animated():
            valid = False
            log.error('image at %s is animated' % abs_url)
        if valid:
            img_format = im.img.format
    return valid, img_format


def _resize_image(old_im, size):
    new_dest = tempfile.NamedTemporaryFile()
    new_dest.close()
    resize_image(old_im.name, new_dest.name, locally=True)
    return new_dest


def _store_image(im_src, product_icon, read_size):
    with open(im_src.name, 'rb') as src:
        with storage.open(product_icon.storage_path(), 'wb') as fp:
            while True:
                chunk = src.read(read_size)
                if not chunk:
                    break
                else:
                    fp.write(chunk)
