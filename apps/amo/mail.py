import logging

from django.core.mail.backends.base import BaseEmailBackend

from amo.models import FakeEmail

log = logging.getLogger('z.amo.mail')


class FakeEmailBackend(BaseEmailBackend):
    """
    Used for development environments when we don't want to send out
    real emails. This gets swapped in as the email backend when
    `settings.SEND_REAL_EMAIL` is disabled.
    """

    def send_messages(self, messages):
        """Sends a list of messages (saves `FakeEmail` objects)."""
        log.debug('Sending fake mail.')
        for msg in messages:
            FakeEmail.objects.create(message=msg.message().as_string())
        return len(messages)

    def view_all(self):
        """Useful for displaying messages in admin panel."""
        return (FakeEmail.objects.values_list('message', flat=True)
                .order_by('-created'))

    def clear(self):
        return FakeEmail.objects.all().delete()
