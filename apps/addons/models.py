from django.db import models

import amo
from users.models import User


class Addon(amo.LegacyModel):
    name = amo.TranslatedField()
    users = models.ManyToManyField(User)

    class Meta:
        db_table = 'addons'

    def get_absolute_url(self):
        # XXX: use reverse
        return '/addon/%s' % self.id
