import logging

from celeryutils import task

import amo
from amo.decorators import write
from mkt.inapp_pay.models import InappConfig
from mkt.inapp_pay.utils import send_pay_notice
from stats.models import Contribution

log = logging.getLogger('z.purchase.bluevia')
notify_kw = dict(default_retry_delay=15,  # seconds
                 max_tries=5)


@task(**notify_kw)
@write
def purchase_notify(signed_notice, contrib_id, **kw):
    """
    Notify the app of a successful B2G app purchase.
    """
    _notify(signed_notice, contrib_id, purchase_notify)


@task(**notify_kw)
@write
def chargeback_notify(signed_notice, contrib_id, **kw):
    """
    Notify the app of a chargeback for B2G app purchase.
    """
    _notify(signed_notice, contrib_id, chargeback_notify)


def _notify(signed_notice, contrib_id, notifier_task):
    contrib = Contribution.objects.get(pk=contrib_id)
    qs = InappConfig.objects.filter(addon=contrib.addon)
    if not qs.exists():
        log.info('bluevia notice not sent. addon %s for contrib %s is not '
                 'configured for notices' % (contrib.addon.pk,
                                             contrib.pk))
        return
    config = qs.get()
    if contrib.type == amo.CONTRIB_PURCHASE:
        notice_type = amo.INAPP_NOTICE_PAY
    elif contrib.type == amo.CONTRIB_CHARGEBACK:
        notice_type = amo.INAPP_NOTICE_CHARGEBACK
    else:
        raise ValueError('contrib %s has an unknown notification type'
                         % contrib.type)
    url, success, last_error = send_pay_notice(notice_type, signed_notice,
                                               config, contrib, notifier_task)
    if not success:
        log.error('bluevia notice about contrib %s for app %s at %s failed %s'
                  % (contrib.pk, contrib.addon.pk, url, last_error))
