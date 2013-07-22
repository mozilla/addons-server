import logging
from celeryutils import task

from comm.utils import save_from_email_reply


log = logging.getLogger('z.task')


@task
def consume_email(email_text, **kwargs):
    """Parse emails and save notes."""
    res = save_from_email_reply(email_text)
    if not res:
        log.error('Failed to save email.')
