from django.db import models

import amo


class Group(amo.ModelBase):

    name = models.CharField(max_length=255, default='')
    rules = models.TextField()
    users = models.ManyToManyField('users.User', db_table='groups_users')

    class Meta:
        db_table = 'groups'

    def __unicode__(self):
        return self.name
