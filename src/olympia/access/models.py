from django.db import models
from django import dispatch
from django.db.models import signals
import commonware.log

from olympia import amo
from olympia.models import ModelBase


log = commonware.log.getLogger('z.users')


class Group(ModelBase):

    name = models.CharField(max_length=255, default='')
    rules = models.TextField()
    users = models.ManyToManyField('users.UserProfile', through='GroupUser',
                                   related_name='groups')
    notes = models.TextField(blank=True)

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
    if kw.get('raw'):
        return

    amo.log(amo.LOG.GROUP_USER_ADDED, instance.group, instance.user)
    log.info('Added %s to %s' % (instance.user, instance.group))


@dispatch.receiver(signals.post_delete, sender=GroupUser,
                   dispatch_uid='groupuser.post_delete')
def groupuser_post_delete(sender, instance, **kw):
    if kw.get('raw'):
        return

    amo.log(amo.LOG.GROUP_USER_REMOVED, instance.group, instance.user)
    log.info('Removed %s from %s' % (instance.user, instance.group))
