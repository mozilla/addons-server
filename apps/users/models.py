from datetime import datetime

from django.db import models
from django.contrib.auth.models import User

import amo
from translations.fields import TranslatedField


class UserProfile(amo.ModelBase):

    nickname = models.CharField(max_length=255, unique=True, default='')
    firstname = models.CharField(max_length=255, default='')
    lastname = models.CharField(max_length=255, default='')
    password = models.CharField(max_length=255, default='')
    email = models.EmailField(unique=True)

    averagerating = models.CharField(max_length=255, blank=True)
    bio = TranslatedField()
    confirmationcode = models.CharField(max_length=255, default='')
    deleted = models.BooleanField(default=True)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)
    emailhidden = models.BooleanField(default=False)
    homepage = models.CharField(max_length=765, blank=True, default='')
    location = models.CharField(max_length=765, blank=True, default='')
    notes = models.TextField(blank=True)
    notifycompat = models.BooleanField(default=True)
    notifyevents = models.BooleanField(default=True)
    occupation = models.CharField(max_length=765, default='')
    picture_type = models.CharField(max_length=75, default='')
    resetcode = models.CharField(max_length=255, default='')
    resetcode_expires = models.DateTimeField(default=datetime.now)
    sandboxshown = models.BooleanField(default=False)

    user = models.ForeignKey(User, null=True)

    class Meta:
        db_table = 'users'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.display_name)

    def get_absolute_url(self):
        # XXX: use reverse
        return '/users/%s' % self.id

    @property
    def display_name(self):
        if not self.nickname:
            return '%s %s' % (self.firstname, self.lastname)
        else:
            return self.nickname

    @property
    def welcome_name(self):
        if self.firstname:
            return self.firstname
        elif self.nickname:
            return self.nickname
        elif self.lastname:
            return self.lastname

        return ''

    def save(self, force_insert=False, force_update=False):
        # we have to fix stupid things that we defined poorly in remora
        if self.resetcode_expires is None:
            self.resetcode_expires = datetime.now()

        super(UserProfile, self).save(force_insert, force_update)
