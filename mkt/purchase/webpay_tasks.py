import logging

from celeryutils import task
from jingo.helpers import datetime
from tower import ugettext as _

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from mkt.inapp_pay.models import InappConfig
from mkt.inapp_pay.utils import send_pay_notice
from stats.models import Contribution

log = logging.getLogger('z.purchase.webpay')
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
        log.info('webpay notice not sent. addon %s for contrib %s is not '
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
        log.error('webpay notice about contrib %s for app %s at %s failed %s'
                  % (contrib.pk, contrib.addon.pk, url, last_error))


@task
def send_purchase_receipt(contrib_id, **kw):
    """
    Sends an email to the purchaser of the app.
    """
    contrib = Contribution.objects.get(pk=contrib_id)
    with contrib.user.activate_lang():
        # L10n: {0} is the app name.
        subject = _('Receipt for {0}').format(contrib.addon.name)
        data = {
            'app_name': contrib.addon.name,
            'authors': ', '.join([author.display_name
                                  for author in contrib.addon.authors.all()]),
            'date': datetime(contrib.created.date()),
            'purchases': absolutify('/purchases'),
            'support_url': contrib.addon.support_url,
            'terms_of_service_url': absolutify(reverse('site.terms')),
            'transaction_id': contrib.uuid
        }

        log.info('Sending email about purchase: %s' % contrib_id)
        send_mail_jinja(subject, 'purchase/receipt.txt', data,
                        recipient_list=[contrib.user.email])
