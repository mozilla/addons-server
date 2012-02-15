from django.db import models
from django import dispatch
from django.db.models import signals

import amo.models


class Group(amo.models.ModelBase):

    name = models.CharField(max_length=255, default='')
    rules = models.TextField()
    users = models.ManyToManyField('users.UserProfile', through='GroupUser',
                                   related_name='groups')

    class Meta:
        db_table = 'groups'

    def __unicode__(self):
        return self.name


class GroupUser(models.Model):

    group = models.ForeignKey(Group)
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = u'groups_users'


@dispatch.receiver(signals.post_save, sender=GroupUser,
                   dispatch_uid='groupuser.post_save')
def groupuser_post_save(sender, instance, **kw):
    if (not kw.get('raw') and instance.user.user and
        instance.user.groups.filter(rules='*:*').count()):
        instance.user.user.is_superuser = instance.user.user.is_staff = True
        instance.user.user.save()


@dispatch.receiver(signals.post_delete, sender=GroupUser,
                   dispatch_uid='groupuser.post_delete')
def groupuser_post_delete(sender, instance, **kw):
    if (not kw.get('raw') and instance.user.user and
        not instance.user.groups.filter(rules='*:*').count()):
        instance.user.user.is_superuser = instance.user.user.is_staff = False
        instance.user.user.save()
