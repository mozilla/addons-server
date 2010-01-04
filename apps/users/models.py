from datetime import datetime

from django.db import models

import amo
from translations.fields import TranslatedField


class User(amo.ModelBase):

    email = models.EmailField(unique=True)
    firstname = models.CharField(max_length=255, default='')
    lastname = models.CharField(max_length=255, default='')
    nickname = models.CharField(max_length=255, unique=True, null=True)
    password = models.CharField(max_length=255, default='')

    bio = TranslatedField()
    location = models.CharField(max_length=255, default='')
    occupation = models.CharField(max_length=255, default='')
    picture_type = models.CharField(max_length=25, default='')
    homepage = models.CharField(max_length=255, default='')

    emailhidden = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)

    confirmationcode = models.CharField(max_length=255)
    resetcode = models.CharField(max_length=255)
    resetcode_expires = models.DateTimeField(default=datetime.now)

    notifycompat = models.BooleanField(default=True)
    notifyevents = models.BooleanField(default=True)

    deleted = models.BooleanField(default=True)

    notes = models.TextField()
    averagerating = models.CharField(max_length=255, blank=True, default='')


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
