from django.db import models

import amo


class User(amo.LegacyModel):

    email = models.EmailField()
    firstname = models.CharField(max_length=255)
    lastname = models.CharField(max_length=255)
    nickname = models.CharField(max_length=255)

    class Meta:
        db_table = 'users'

    def get_absolute_url(self):
        # XXX: use reverse
        return '/users/%s' % self.id

    @property
    def display_name(self):
        if not self.nickname:
            return '%s %s' % (self.firstname, self.lastname)
        else:
            return self.nickname
