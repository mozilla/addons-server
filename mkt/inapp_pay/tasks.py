import calendar
from datetime import datetime, timedelta
import logging
import os
import tempfile
import time

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction

from celeryutils import task
import jwt
import requests

import amo
from amo.decorators import write
from amo.utils import ImageCheck, resize_image

from .models import InappPayment, InappPayNotice, InappImage, InappConfig
from .utils import send_pay_notice

log = logging.getLogger('z.inapp_pay.tasks')
notify_kw = dict(default_retry_delay=15,  # seconds
                 max_tries=5)


@task(**notify_kw)
@write
def payment_notify(payment_id, **kw):
    """Notify the app of a successful payment.

    payment_id: pk of InappPayment
    """
    log.debug('sending payment notice for payment %s' % payment_id)
    _notify(payment_id, amo.INAPP_NOTICE_PAY, payment_notify)


@task(**notify_kw)
@write
def chargeback_notify(payment_id, reason, **kw):
    """Notify the app of a chargeback.

    payment_id: pk of InappPayment
    reason: either 'reversal' or 'refund'
    """
    log.debug('sending chargeback notice for payment %s, reason %r'
              % (payment_id, reason))
    _notify(payment_id, amo.INAPP_NOTICE_CHARGEBACK,
            chargeback_notify,
            extra_response={'reason': reason})


def _notify(payment_id, notice_type, notifier_task, extra_response=None):
    payment = InappPayment.objects.get(pk=payment_id)
    config = payment.config
    contrib = payment.contribution
    if notice_type == amo.INAPP_NOTICE_PAY:
        typ = 'mozilla/payments/pay/postback/v1'
    elif notice_type == amo.INAPP_NOTICE_CHARGEBACK:
        typ = 'mozilla/payments/pay/chargeback/v1'
    else:
        raise NotImplementedError('Unknown type: %s' % notice_type)
    response = {'transactionID': contrib.pk}
    if extra_response:
        response.update(extra_response)
    issued_at = calendar.timegm(time.gmtime())
    signed_notice = jwt.encode({'iss': settings.INAPP_MARKET_ID,
                                'aud': config.public_key,  # app ID
                                'typ': typ,
                                'iat': issued_at,
                                'exp': issued_at + 3600,  # expires in 1 hour
                                'request': {'priceTier': contrib.price_tier.pk,
                                            'name': payment.name,
                                            'description': payment.description,
                                            'productdata': payment.app_data},
                                'response': response},
                               config.get_private_key(),
                               algorithm='HS256')
    url, success, last_error = send_pay_notice(notice_type, signed_notice,
                                               config, contrib, notifier_task)

    s = InappPayNotice._meta.get_field_by_name('last_error')[0].max_length
    last_error = last_error[:s]  # truncate to fit
    InappPayNotice.objects.create(payment=payment,
                                  notice=notice_type,
                                  success=success,
                                  url=url,
                                  last_error=last_error)


@task
@transaction.commit_on_success
def fetch_product_image(config_id, app_req, read_size=100000, **kw):
    config = InappConfig.objects.get(pk=config_id)
    url = app_req['request'].get('imageURL')
    if not url:
        log.info(u'in-app product %r for config %s does not have an image URL'
                 % (app_req['request']['name'], config.pk))
        return
    params = dict(config=config, image_url=url)
    try:
        product = InappImage.objects.get(**params)
    except InappImage.DoesNotExist:
        product = InappImage.objects.create(processed=False,
                                            valid=False,
                                            **params)
    now = datetime.now()
    if product.valid and product.modified > now - timedelta(days=5):
        log.info('Already have valid, recent image for config %s at URL %s'
                 % (config.pk, url))
        return

    abs_url = product.absolute_image_url()
    tmp_dest = tempfile.NamedTemporaryFile(delete=False)
    try:
        res = requests.get(abs_url, timeout=5)
        res.raise_for_status()
        im_src = res.raw
        done = False
        while not done:
            chunk = im_src.read(read_size)
            if not chunk:
                done = True
            else:
                tmp_dest.write(chunk)
    except AssertionError:
        raise  # Raise test-related exceptions.
    except:
        tmp_dest.close()
        os.unlink(tmp_dest.name)
        log.error('fetch_product_image error with '
                  '%s for config %s' % (abs_url, config.pk),
                  exc_info=True)
        return
    else:
        tmp_dest.close()

    try:
        valid, img_format = _check_image(tmp_dest.name, abs_url, config)
        if valid:
            log.info('resizing in-app image for config %s URL %s'
                     % (config.pk, url))
            tmp_dest = _resize_image(tmp_dest)

        product.update(processed=True, valid=valid,
                       image_format=img_format)

        if valid:
            _store_image(tmp_dest, product, read_size)
    finally:
        os.unlink(tmp_dest.name)


def _check_image(im_path, abs_url, config):
    valid = True
    img_format = ''
    with open(im_path, 'rb') as fp:
        im = ImageCheck(fp)
        if not im.is_image():
            valid = False
            log.error('image at %s for config %s is not an image'
                      % (abs_url, config.pk))
        if im.is_animated():
            valid = False
            log.error('image at %s for config %s is animated'
                      % (abs_url, config.pk))
        if valid:
            img_format = im.img.format
    return valid, img_format


def _resize_image(old_im):
    new_dest = tempfile.NamedTemporaryFile()
    new_dest.close()
    resize_image(old_im.name, new_dest.name,
                 size=settings.INAPP_IMAGE_SIZE, locally=True)
    return new_dest


def _store_image(im_src, product, read_size):
    with open(im_src.name, 'rb') as src:
        with storage.open(product.path(), 'wb') as fp:
            done = False
            while not done:
                chunk = src.read(read_size)
                if not chunk:
                    done = True
                else:
                    fp.write(chunk)
