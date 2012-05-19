import logging

from django.core.mail.backends.base import BaseEmailBackend
from django.db import models

from amo.models import ModelBase

log = logging.getLogger('z.amo.mail')


class FakeEmail(ModelBase):
    message = models.TextField()

    class Meta:
        db_table = 'fake_email'


class FakeEmailBackend(BaseEmailBackend):

    def send_messages(self, messages):
        log.debug('Sending fake mail.')
        for msg in messages:
            FakeEmail.objects.create(message=msg.message().as_string())

    def view_all(self):
        return (FakeEmail.objects.values_list('message', flat=True)
                .order_by('id'))

    def clear(self):
        return FakeEmail.objects.all().delete()
