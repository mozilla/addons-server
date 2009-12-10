from django.db import models

import amo
from translations.fields import TranslatedField


class Addon(amo.ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    users = models.ManyToManyField('users.User')

    class Meta:
        db_table = 'addons'

    def get_absolute_url(self):
        # XXX: use reverse
        return '/addon/%s' % self.id
