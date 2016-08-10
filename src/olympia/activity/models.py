import uuid

from django.db import models

import commonware.log

from olympia.amo.models import ModelBase
from olympia.versions.models import Version

log = commonware.log.getLogger('z.devhub')

# Number of times a token can be used.
MAX_TOKEN_USE_COUNT = 100


class ActivityLogToken(ModelBase):
    version = models.ForeignKey(Version, related_name='token')
    user = models.ForeignKey('users.UserProfile',
                             related_name='activity_log_tokens')
    uuid = models.UUIDField(default=lambda: uuid.uuid4().hex, unique=True)
    use_count = models.IntegerField(
        default=0,
        help_text='Stores the number of times the token has been used')

    class Meta:
        db_table = 'log_activity_tokens'
        unique_together = ('version', 'user')

    def is_expired(self):
        return self.use_count >= MAX_TOKEN_USE_COUNT

    def is_valid(self):
        return (not self.is_expired() and
                self.version.addon.latest_version == self.version)

    def expire(self):
        self.update(use_count=MAX_TOKEN_USE_COUNT)

    def increment_use(self):
        self.__class__.objects.filter(pk=self.pk).update(
            use_count=models.expressions.F('use_count') + 1)
        self.use_count = self.use_count + 1
