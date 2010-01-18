from datetime import datetime
import hashlib
import random
import string

from django.db import models
from django.contrib.auth.models import User as DjangoUser

import amo
from translations.fields import TranslatedField


def get_hexdigest(algorithm, salt, raw_password):
    return hashlib.new(algorithm, salt + raw_password).hexdigest()


def rand_string(length):
    return ''.join(random.choice(string.letters) for i in xrange(length))


def create_password(algorithm, raw_password):
    salt = get_hexdigest(algorithm, rand_string(12), rand_string(12))[:64]
    hsh = get_hexdigest(algorithm, salt, raw_password)
    return '$'.join([algorithm, salt, hsh])


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

    user = models.ForeignKey(DjangoUser, null=True)

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

    def save(self, force_insert=False, force_update=False, using=None):
        # we have to fix stupid things that we defined poorly in remora
        if self.resetcode_expires is None:
            self.resetcode_expires = datetime.now()

        super(UserProfile, self).save(force_insert, force_update, using)

    def check_password(self, raw_password):
        if '$' not in self.password:
            valid = (get_hexdigest('md5', '', raw_password) == self.password)
            if valid:
                # Upgrade an old password.
                self.set_password(raw_password)
                self.save()
            return valid

        algo, salt, hsh = self.password.split('$')
        return hsh == get_hexdigest(algo, salt, raw_password)

    def set_password(self, raw_password, algorithm='sha512'):
        self.password = create_password(algorithm, raw_password)

    def create_django_user(self):
        """Make a django.contrib.auth.User for this UserProfile."""
        # Reusing the id will make our life easier, because we can use the
        # OneToOneField as pk for Profile linked back to the auth.user
        # in the future.
        self.user = User(id=self.pk)
        self.user.first_name = self.firstname
        self.user.last_name = self.lastname
        self.user.username = self.email
        self.user.email = self.email
        self.user.password = self.password
        self.user.date_joined = self.created

        if self.group_set.filter(rules='*:*').count():
            self.user.is_superuser = self.user.is_staff = True

        self.user.save()
        self.save()
        return self.user
