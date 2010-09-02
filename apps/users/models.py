from datetime import datetime
import hashlib
import os
import random
import re
import string
import time

from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.core.mail import send_mail
from django.db import models
from django.template import Context, loader
from django.utils.encoding import smart_unicode

import caching.base as caching
import commonware.log
from tower import ugettext as _

import amo
import amo.models
from amo.urlresolvers import reverse
from translations.fields import PurifiedField

log = commonware.log.getLogger('z.users')


def get_hexdigest(algorithm, salt, raw_password):
    return hashlib.new(algorithm, salt + raw_password).hexdigest()


def rand_string(length):
    return ''.join(random.choice(string.letters) for i in xrange(length))


def create_password(algorithm, raw_password):
    salt = get_hexdigest(algorithm, rand_string(12), rand_string(12))[:64]
    hsh = get_hexdigest(algorithm, salt, raw_password)
    return '$'.join([algorithm, salt, hsh])


class UserManager(amo.models.ManagerBase):

    def request_user(self):
        return (self.extra(select={'request': 1})
                .transform(UserProfile.request_user_transformer))


class UserProfile(amo.models.ModelBase):

    nickname = models.CharField(max_length=255, default='', null=True,
                                blank=True)
    firstname = models.CharField(max_length=255, default='', blank=True)
    lastname = models.CharField(max_length=255, default='', blank=True)

    username = models.CharField(max_length=255, default='', unique=True)
    display_name = models.CharField(max_length=255, default='', null=True,
                                    blank=True)

    password = models.CharField(max_length=255, default='')
    email = models.EmailField(unique=True)

    averagerating = models.CharField(max_length=255, blank=True, null=True)
    bio = PurifiedField()
    confirmationcode = models.CharField(max_length=255, default='',
                                        blank=True)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)
    emailhidden = models.BooleanField(default=False)
    homepage = models.URLField(max_length=255, blank=True, default='',
                               verify_exists=False, error_messages={
                               'invalid': _('This URL has an invalid format. '
                                            'Valid URLs look like '
                                            'http://example.com/my_page.')})
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, null=True)
    notifycompat = models.BooleanField(default=True)
    notifyevents = models.BooleanField(default=True)
    occupation = models.CharField(max_length=255, default='', blank=True)
    # This is essentially a "has_picture" flag right now
    picture_type = models.CharField(max_length=75, default='', blank=True)
    resetcode = models.CharField(max_length=255, default='', blank=True)
    resetcode_expires = models.DateTimeField(default=datetime.now, null=True,
                                             blank=True)
    sandboxshown = models.BooleanField(default=False)
    last_login_ip = models.CharField(default='', max_length=45, editable=False)
    last_login_attempt = models.DateTimeField(null=True, editable=False)
    last_login_attempt_ip = models.CharField(default='', max_length=45,
                                             editable=False)
    failed_login_attempts = models.PositiveIntegerField(default=0,
                                                        editable=False)

    user = models.ForeignKey(DjangoUser, null=True, editable=False, blank=True)

    objects = UserManager()

    class Meta:
        db_table = 'users'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.display_name or self.username)

    def get_url_path(self):
        return reverse('users.profile', args=[self.id])

    def flush_urls(self):
        urls = ['*/user/%d/' % self.id]

        return urls

    @amo.cached_property
    def addons_listed(self):
        """Public add-ons this user is listed as author of."""
        return self.addons.valid().filter(addonuser__listed=True).distinct()

    @property
    def picture_dir(self):
        split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(self.id))
        return os.path.join(settings.USERPICS_PATH, split_id.group(2) or '0',
                            split_id.group(1) or '0')

    @property
    def picture_path(self):
        return os.path.join(self.picture_dir, str(self.id) + '.png')

    @property
    def picture_url(self):
        if not self.picture_type:
            return settings.MEDIA_URL + '/img/zamboni/anon_user.png'
        else:
            split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(self.id))
            return settings.USERPICS_URL % (
                split_id.group(2) or 0, split_id.group(1) or 0, self.id,
                int(time.mktime(self.modified.timetuple())))

    @amo.cached_property
    def is_developer(self):
        return bool(self.addons.filter(authors=self,
                                       addonuser__listed=True)[:1])

    @property
    def name(self):
        return self.display_name or self.username

    welcome_name = name

    @amo.cached_property
    def reviews(self):
        """All reviews that are not dev replies."""
        return self._reviews_all.filter(reply_to=None)

    def anonymize(self):
        log.info(u"User (%s: <%s>) is being anonymized." % (self, self.email))
        self.email = ""
        self.password = "sha512$Anonymous$Password"
        self.firstname = ""
        self.lastname = ""
        self.nickname = None
        self.username = "Anonymous-%s" % self.id  # Can't be null
        self.display_name = None
        self.homepage = ""
        self.deleted = True
        self.picture_type = ""
        self.save()

    def generate_confirmationcode(self):
        if not self.confirmationcode:
            self.confirmationcode = ''.join(random.sample(string.letters +
                                                          string.digits, 60))
        return self.confirmationcode

    def save(self, force_insert=False, force_update=False, using=None):
        # we have to fix stupid things that we defined poorly in remora
        if not self.resetcode_expires:
            self.resetcode_expires = datetime.now()

        delete_user = None
        if self.deleted and self.user:
            delete_user = self.user
            self.user = None
            # Delete user after saving this profile.

        super(UserProfile, self).save(force_insert, force_update, using)

        if self.deleted and delete_user:
            delete_user.delete()

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

    def log_login_attempt(self, request, successful):
        """Log a user's login attempt"""
        self.last_login_attempt = datetime.now()
        self.last_login_attempt_ip = request.META['REMOTE_ADDR']

        if successful:
            log.debug(u"User (%s) logged in successfully" % self)
            self.failed_login_attempts = 0
            self.last_login_ip = request.META['REMOTE_ADDR']
        else:
            log.debug(u"User (%s) failed to log in" % self)
            if self.failed_login_attempts < 16777216:
                self.failed_login_attempts += 1

        self.save()

    def create_django_user(self):
        """Make a django.contrib.auth.User for this UserProfile."""
        # Reusing the id will make our life easier, because we can use the
        # OneToOneField as pk for Profile linked back to the auth.user
        # in the future.
        self.user = DjangoUser(id=self.pk)
        self.user.first_name = ''
        self.user.last_name = ''
        self.user.username = self.email  # f
        self.user.email = self.email
        self.user.password = self.password
        self.user.date_joined = self.created

        if self.groups.filter(rules='*:*').count():
            self.user.is_superuser = self.user.is_staff = True

        self.user.save()
        self.save()
        return self.user

    def mobile_collection(self):
        return self.special_collection(amo.COLLECTION_MOBILE,
            defaults={'slug': 'mobile', 'listed': False,
                      'name': _('My Mobile Add-ons')})

    def favorites_collection(self):
        return self.special_collection(amo.COLLECTION_FAVORITES,
            defaults={'slug': 'favorites', 'listed': False,
                      'name': _('My Favorite Add-ons')})

    def special_collection(self, type_, defaults):
        from bandwagon.models import Collection
        c, _ = Collection.objects.get_or_create(
            author=self, type=type_, defaults=defaults)
        return c

    @staticmethod
    def request_user_transformer(users):
        """Adds extra goodies to a UserProfile (meant for request.amo_user)."""
        # We don't want to cache these things on every UserProfile; they're
        # only used by a user attached to a request.
        from bandwagon.models import CollectionAddon, CollectionWatcher
        SPECIAL = amo.COLLECTION_SPECIAL_SLUGS.keys()
        user = users[0]
        qs = CollectionAddon.objects.filter(
            collection__author=user, collection__type__in=SPECIAL)
        addons = dict((type_, []) for type_ in SPECIAL)
        for addon, ctype in qs.values_list('addon', 'collection__type'):
            addons[ctype].append(addon)
        user.mobile_addons = addons[amo.COLLECTION_MOBILE]
        user.favorite_addons = addons[amo.COLLECTION_FAVORITES]
        user.watching = list((CollectionWatcher.objects.filter(user=user)
                             .values_list('collection', flat=True)))


class BlacklistedUsername(amo.models.ModelBase):
    """Blacklisted user usernames."""
    username = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'users_blacklistedusername'

    def __unicode__(self):
        return self.username

    @classmethod
    def blocked(cls, username):
        """Check to see if a username is in the (cached) blacklist."""
        username = smart_unicode(username).lower()
        qs = cls.objects.all()
        f = lambda: [u.lower() for u in qs.values_list('username', flat=True)]
        blacklist = caching.cached_with(qs, f, 'blocked')
        return username in blacklist


class PersonaAuthor(unicode):
    """Stub user until the persona authors get imported."""

    @property
    def id(self):
        """I don't want to change code depending on PersonaAuthor.id, so I'm
        just hardcoding 0.  The only code using this is flush_urls."""
        return 0

    @property
    def name(self):
        return self

    display_name = name
