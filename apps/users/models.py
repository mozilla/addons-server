from datetime import datetime
import hashlib
import logging
import random
import re
import string
import time

from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.core.mail import send_mail
from django.db import models
from django.template import Context, loader

import amo
import amo.models

from amo.urlresolvers import reverse
from l10n import ugettext as _
from translations.fields import PurifiedField

log = logging.getLogger('z.users')


def get_hexdigest(algorithm, salt, raw_password):
    return hashlib.new(algorithm, salt + raw_password).hexdigest()


def rand_string(length):
    return ''.join(random.choice(string.letters) for i in xrange(length))


def create_password(algorithm, raw_password):
    salt = get_hexdigest(algorithm, rand_string(12), rand_string(12))[:64]
    hsh = get_hexdigest(algorithm, salt, raw_password)
    return '$'.join([algorithm, salt, hsh])


class UserProfile(amo.models.ModelBase):

    nickname = models.CharField(max_length=255, unique=True, default='',
                                null=True, blank=True)
    firstname = models.CharField(max_length=255, default='', blank=True)
    lastname = models.CharField(max_length=255, default='', blank=True)
    password = models.CharField(max_length=255, default='')
    email = models.EmailField(unique=True)

    averagerating = models.CharField(max_length=255, blank=True)
    bio = PurifiedField()
    confirmationcode = models.CharField(max_length=255, default='',
                                        blank=True)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)
    emailhidden = models.BooleanField(default=False)
    homepage = models.CharField(max_length=255, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True)
    notifycompat = models.BooleanField(default=True)
    notifyevents = models.BooleanField(default=True)
    occupation = models.CharField(max_length=255, default='', blank=True)
    picture_type = models.CharField(max_length=75, default='', blank=True)
    resetcode = models.CharField(max_length=255, default='', blank=True)
    resetcode_expires = models.DateTimeField(default=datetime.now,
                                             blank=True)
    sandboxshown = models.BooleanField(default=False)

    user = models.ForeignKey(DjangoUser, null=True, editable=False, blank=True)

    class Meta:
        db_table = 'users'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.display_name)

    def get_url_path(self):
        return reverse('users.profile', args=[self.id])

    @amo.cached_property
    def addons_listed(self):
        """public add-ons this user is listed as author of"""
        return self.addons.valid().filter(addonuser__listed=True)

    @property
    def name(self):
        """Can be used while we're transitioning from separate first/last names
        to a single field.  Bug 546818#6"""
        return ('%s %s' % (self.firstname, self.lastname)).strip()

    @property
    def picture_url(self):
        split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(self.id))
        if not self.picture_type:
            return settings.MEDIA_URL + '/img/zamboni/anon_user.png'
        else:
            return settings.USER_PIC_URL % (
                split_id.group(2) or 0, split_id.group(1) or 0, self.id,
                int(time.mktime(self.modified.timetuple())))

    @amo.cached_property
    def is_developer(self):
        return bool(self.addons.filter(authors=self,
                                       addonuser__listed=True)[:1])

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

    @amo.cached_property
    def reviews(self):
        """All reviews that are not dev replies."""
        return self._reviews_all.filter(reply_to=None)

    def anonymize(self):
        log.info("User (%s: <%s>) is being anonymized." % (self, self.email))
        self.email = ""
        self.password = "sha512$Anonymous$Password"
        self.firstname = ""
        self.lastname = ""
        self.nickname = None
        self.homepage = ""
        self.deleted = True
        self.picture_type = ""
        self.save()

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

    def email_confirmation_code(self):
        log.debug("Sending account confirmation code for user (%s)", self)

        url = "%s%s" % (settings.SITE_URL,
                        reverse('users.confirm',
                                args=[self.id, self.confirmationcode]))
        domain = settings.DOMAIN
        t = loader.get_template('users/email/confirm.ltxt')
        c = {'domain': domain, 'url': url, }
        send_mail(_("Please confirm your email address"),
                  t.render(Context(c)), None, [self.email])

    def create_django_user(self):
        """Make a django.contrib.auth.User for this UserProfile."""
        # Reusing the id will make our life easier, because we can use the
        # OneToOneField as pk for Profile linked back to the auth.user
        # in the future.
        self.user = DjangoUser(id=self.pk)
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
