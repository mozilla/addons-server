import logging

from celeryutils import task
from jingo.helpers import datetime
from tower import ugettext as _

from amo.helpers import absolutify
from amo.utils import get_locale_from_lang, send_html_mail_jinja
from stats.models import Contribution

log = logging.getLogger('z.purchase.webpay')
notify_kw = dict(default_retry_delay=15,  # seconds
                 max_tries=5)


@task
def send_purchase_receipt(contrib_id, **kw):
    """
    Sends an email to the purchaser of the app.
    """
    contrib = Contribution.objects.get(pk=contrib_id)

    with contrib.user.activate_lang():
        addon = contrib.addon
        version = addon.current_version or addon.latest_version
        # L10n: {0} is the app name.
        subject = _('Receipt for {0}').format(contrib.addon.name)
        data = {
            'app_name': addon.name,
            'developer_name': version.developer_name if version else '',
            'price': contrib.get_amount_locale(get_locale_from_lang(
                contrib.source_locale)),
            'date': datetime(contrib.created.date()),
            'purchaser_email': contrib.user.email,
            #'purchaser_phone': '',  # TODO: See bug 894614.
            #'purchaser_last_four': '',
            'transaction_id': contrib.uuid,
            'purchases_url': absolutify('/purchases'),
            'support_url': addon.support_url,
            'terms_of_service_url': absolutify('/terms-of-use'),
        }

        log.info('Sending email about purchase: %s' % contrib_id)
        text_template = 'purchase/receipt.ltxt'
        html_template = 'purchase/receipt.html'
        send_html_mail_jinja(subject, html_template, text_template, data,
                             recipient_list=[contrib.user.email])
