import logging

from amo.utils import send_mail_jinja

from celeryutils import task
from tower import ugettext as _


log = logging.getLogger('z.mkt.developers.task')


@task
def email_buyer_refund(contrib):
    # Email buyer.
    send_mail_jinja(_('The refund request for %s is being '
                      'processed' % contrib.addon.name),
                    'support/emails/refund-approved.txt',
                    {'name': contrib.addon.name},
                    recipient_list=[contrib.user.email]),
