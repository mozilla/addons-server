import calendar
import logging
import time
from urllib2 import urlopen
import urlparse

from django.conf import settings

from celeryutils import task
import jwt

import amo
from amo.decorators import write

from .models import InappPayment, InappPayNotice

log = logging.getLogger('z.inapp_pay.tasks')


@task
@write
def notify_app(notice, payment_id, **kw):
    payment = InappPayment.objects.get(pk=payment_id)
    config = payment.config
    contrib = payment.contribution
    url = urlparse.urlunparse((config.app_protocol(), config.addon.app_domain,
                               config.postback_url, '', '', ''))
    exception = None
    success = False
    issued_at = calendar.timegm(time.gmtime())
    signed_notice = jwt.encode({'iss': settings.INAPP_MARKET_ID,
                                'aud': config.public_key,  # app ID
                                'typ': 'mozilla/payments/pay/postback/v1',
                                'iat': issued_at,
                                'exp': issued_at + 3600,  # expires in 1 hour
                                'request': {'price': str(contrib.amount),
                                            'currency': contrib.currency,
                                            'name': payment.name,
                                            'description': payment.description,
                                            'productdata': payment.app_data},
                                'response': {'transactionID': contrib.pk}},
                               config.private_key,
                               algorithm='HS256')
    try:
        res = urlopen(url, signed_notice, timeout=5)
        res_content = res.read().strip()
    except AssertionError:
        raise  # Raise test-related exceptions.
    except Exception, exception:
        log.error('In-app payment %s raised exception in URL %s'
                  % (payment.pk, url), exc_info=True)
    else:
        if res_content == str(contrib.pk):
            success = True
            log.debug('app config %s responded OK for in-app payment %s'
                      % (config.pk, payment.pk))
        else:
            log.error('app config %s did not respond with contribution ID %s '
                      'for in-app payment %s' % (config.pk, contrib.pk,
                                                 payment.pk))
        res.close()

    if exception:
        last_error = u'%s: %s' % (exception.__class__.__name__, exception)
    else:
        last_error = ''
    s = InappPayNotice._meta.get_field_by_name('last_error')[0].max_length
    last_error = last_error[:s]  # truncate to fit

    InappPayNotice.objects.create(payment=payment,
                                  notice=amo.INAPP_NOTICE_PAY,
                                  success=success,
                                  url=url,
                                  last_error=last_error)
