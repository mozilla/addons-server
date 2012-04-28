import re

from django.db import models
from django import dispatch
from django.db.models import signals

import amo.models


class AccessWhitelist(amo.models.ModelBase):
    email = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'access_whitelist'

    def __unicode__(self):
        return u'%s: %s...' % (self.id, self.email[:30])

    @classmethod
    def matches(cls, email):
        """Loop through whitelist and find any matches."""
        for w in AccessWhitelist.objects.all():
            for e in w.email.replace('\r', '').split('\n'):
                # Asterisks become .+ so that we can match wildcards.
                if re.match(re.escape(e).replace('\\*', '.+'), email):
                    return True
        return False


@dispatch.receiver(signals.post_save, sender=AccessWhitelist,
                   dispatch_uid='accesswhitelist.post_save')
def accesswhitelist_post_save(sender, instance, **kw):
    if not kw.get('raw') and instance.email:
        from users.models import UserProfile
        emails = instance.email.replace('\r', '').split('\n')
        # Invalidate users.
        for user in UserProfile.objects.filter(email__in=emails):
            user.save()


class Group(amo.models.ModelBase):

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
