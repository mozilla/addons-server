import logging

from django.core.mail.backends.base import BaseEmailBackend

import redisutils

log = logging.getLogger('z.amo.mail')


class FakeEmailBackend(BaseEmailBackend):
    key = 'amo:mail:fakemail'

    def __init__(self, *args, **kw):
        super(FakeEmailBackend, self).__init__(*args, **kw)
        self.redis = redisutils.connections['master']

    def send_messages(self, messages):
        log.debug('Sending fake mail.')
        for msg in messages:
            self.redis.rpush(self.key, msg.message().as_string())

    def view_all(self):
        return self.redis.lrange(self.key, 0, -1)

    def clear(self):
        return self.redis.delete(self.key)
