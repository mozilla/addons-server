from django.db import models

import amo


class Group(amo.ModelBase):

    name = models.CharField(max_length=255, default='')
    rules = models.TextField()
    users = models.ManyToManyField('users.UserProfile', through='GroupUser')

    class Meta:
        db_table = 'groups'

    def __unicode__(self):
        return self.name


class GroupUser(models.Model):

    group = models.ForeignKey(Group)
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = u'groups_users'
