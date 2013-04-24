from amo.utils import send_mail_jinja

from celeryutils import task


@task
def email_buyer_refund_pending(contrib):
    send_mail_jinja('Your refund request for %s is now being processed'
                    % contrib.addon.name,
                    'lookup/emails/refund-pending.txt',
                    {'name': contrib.addon.name},
                    recipient_list=[contrib.user.email]),


@task
def email_buyer_refund_approved(contrib):
    send_mail_jinja('Your refund request for %s has been approved!'
                    % contrib.addon.name,
                    'lookup/emails/refund-approved.txt',
                    {'name': contrib.addon.name},
                    recipient_list=[contrib.user.email]),
