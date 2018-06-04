from django import dispatch
from django.db import models
from django.db.models import signals

import olympia.core.logger

from olympia import activity, amo
from olympia.amo.models import ModelBase


log = olympia.core.logger.getLogger('z.users')


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

    def invalidate_groups_list(self):
        """Callback to invalidate user.groups_list when creating/deleting GroupUser
        instances for this user."""
        try:
            # groups_list is a @cached_property, delete it to force it to be
            # refreshed (ignore AttributeError, that just means it has not been
            # accessed yet).
            del self.user.groups_list
        except AttributeError:
            pass


@dispatch.receiver(signals.post_save, sender=GroupUser,
                   dispatch_uid='groupuser.post_save')
def groupuser_post_save(sender, instance, **kw):
    if kw.get('raw'):
        return

    activity.log_create(amo.LOG.GROUP_USER_ADDED, instance.group,
                        instance.user)
    log.info('Added %s to %s' % (instance.user, instance.group))
    instance.invalidate_groups_list()


@dispatch.receiver(signals.post_delete, sender=GroupUser,
                   dispatch_uid='groupuser.post_delete')
def groupuser_post_delete(sender, instance, **kw):
    if kw.get('raw'):
        return

    activity.log_create(amo.LOG.GROUP_USER_REMOVED, instance.group,
                        instance.user)
    log.info('Removed %s from %s' % (instance.user, instance.group))
    instance.invalidate_groups_list()
