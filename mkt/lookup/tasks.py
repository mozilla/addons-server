import logging

from amo.utils import send_mail_jinja

from celeryutils import task


log = logging.getLogger('z.mkt.developers.task')


@task
def email_buyer_refund_pending(contrib):
    # Email buyer.
    send_mail_jinja('Your refund request for %s is now being processed'
                    % contrib.addon.name,
                    'support/emails/refund-pending.txt',
                    {'name': contrib.addon.name},
                    recipient_list=[contrib.user.email]),


@task
def email_buyer_refund_approved(contrib):
    # Email buyer.
    send_mail_jinja('Your refund request for %s has been approved!'
                    % contrib.addon.name,
                    'support/emails/refund-approved.txt',
                    {'name': contrib.addon.name},
                    recipient_list=[contrib.user.email]),
