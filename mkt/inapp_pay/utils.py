import logging
import urlparse

import requests

import amo

log = logging.getLogger('z.inapp_pay.utils')


def send_pay_notice(notice_type, signed_notice, config, contrib,
                    notifier_task):
    """
    Send app a notification about a payment or chargeback.

    Parameters:

    **notice_type**
        constant to indicate the type of notification being sent
    **signed_notice**
        encoded JWT with request and response
    **config**
        InappConfig object that specifies notification URLs
    **contrib**
        Contribution instance for the payment in question
    **notifier_task**
        celery task object

    The *signed_notice* will be sent to the URL found in the *config*.
    If there's an error in the app's response, *notifier_task* will be
    retried up to five times.

    A tuple of (url, success, last_error) is returned.

    **url**
        Absolute URL where notification was sent
    **success**
        True if notification was successful
    **last_error**
        String to indicate the last exception message in the case of failure.
    """
    if notice_type == amo.INAPP_NOTICE_PAY:
        uri = config.postback_url
    elif notice_type == amo.INAPP_NOTICE_CHARGEBACK:
        uri = config.chargeback_url
    else:
        raise NotImplementedError('Unknown type: %s' % notice_type)
    url = urlparse.urlunparse((config.app_protocol(),
                               config.addon.parsed_app_domain.netloc, uri, '',
                               '', ''))
    exception = None
    success = False
    try:
        res = requests.post(url, signed_notice, timeout=5)
        res.raise_for_status()  # raise exception for non-200s
        res_content = res.text
    except AssertionError:
        raise  # Raise test-related exceptions.
    except Exception, exception:
        log.error('Notice for contrib %s raised exception in URL %s'
                  % (contrib.pk, url), exc_info=True)
        try:
            notifier_task.retry(exc=exception)
        except:
            log.exception('while retrying contrib %s notice; '
                          'notification URL: %s' % (contrib.pk, url))
    else:
        if res_content == str(contrib.pk):
            success = True
            log.debug('app config %s responded OK for contrib %s notification'
                      % (config.pk, contrib.pk))
        else:
            log.error('app config %s did not respond with contribution ID %s '
                      'for notification' % (config.pk, contrib.pk))
    if exception:
        last_error = u'%s: %s' % (exception.__class__.__name__, exception)
    else:
        last_error = ''

    return url, success, last_error
