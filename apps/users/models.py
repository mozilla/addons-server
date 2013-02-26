from base64 import decodestring
from datetime import datetime
import hashlib
import os
import random
import re
import string
import time

from django import forms, dispatch
from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.core import validators
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.template import Context, loader
from django.utils.encoding import smart_str, smart_unicode
from django.utils.functional import lazy

import caching.base as caching
import commonware.log
from tower import ugettext as _

import amo
import amo.models
from access.models import Group, GroupUser
from amo.urlresolvers import reverse
from translations.fields import PurifiedField
from translations.query import order_by_translation

log = commonware.log.getLogger('z.users')


def get_hexdigest(algorithm, salt, raw_password):
    if 'base64' in algorithm:
        # These are getpersonas passwords with base64 encoded salts.
        salt = decodestring(salt)
        algorithm = algorithm.replace('+base64', '')

    if algorithm.startswith('sha512+MD5'):
        # These are persona specific passwords when we imported
        # users from getpersonas.com. The password is md5 hashed
        # and then sha512'd.
        md5 = hashlib.new('md5', raw_password).hexdigest()
        return hashlib.new('sha512', smart_str(salt + md5)).hexdigest()

    return hashlib.new(algorithm, smart_str(salt + raw_password)).hexdigest()


def rand_string(length):
    return ''.join(random.choice(string.letters) for i in xrange(length))


def create_password(algorithm, raw_password):
    salt = get_hexdigest(algorithm, rand_string(12), rand_string(12))[:64]
    hsh = get_hexdigest(algorithm, salt, raw_password)
    return '$'.join([algorithm, salt, hsh])


class UserForeignKey(models.ForeignKey):
    """
    A replacement for  models.ForeignKey('users.UserProfile').

    This field uses UserEmailField to make form fields key off the user's email
    instead of the primary key id.  We also hook up autocomplete automatically.
    """

    def __init__(self, *args, **kw):
        super(UserForeignKey, self).__init__(UserProfile, *args, **kw)

    def value_from_object(self, obj):
        return getattr(obj, self.name).email

    def formfield(self, **kw):
        defaults = {'form_class': UserEmailField}
        defaults.update(kw)
        return models.Field.formfield(self, **defaults)


class UserEmailField(forms.EmailField):

    def clean(self, value):
        if value in validators.EMPTY_VALUES:
            raise forms.ValidationError(self.error_messages['required'])
        try:
            return UserProfile.objects.get(email=value)
        except UserProfile.DoesNotExist:
            raise forms.ValidationError(_('No user with that email.'))

    def widget_attrs(self, widget):
        lazy_reverse = lazy(reverse, str)
        return {'class': 'email-autocomplete',
                'data-src': lazy_reverse('users.ajax')}


class UserProfile(amo.models.OnChangeMixin, amo.models.ModelBase):
    username = models.CharField(max_length=255, default='', unique=True)
    display_name = models.CharField(max_length=255, default='', null=True,
                                    blank=True)

    password = models.CharField(max_length=255, default='')
    email = models.EmailField(unique=True, null=True)

    averagerating = models.CharField(max_length=255, blank=True, null=True)
    bio = PurifiedField(short=False)
    confirmationcode = models.CharField(max_length=255, default='',
                                        blank=True)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)
    emailhidden = models.BooleanField(default=True)
    homepage = models.URLField(max_length=255, blank=True, default='',
                               verify_exists=False)
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
    read_dev_agreement = models.DateTimeField(null=True, blank=True)

    last_login_ip = models.CharField(default='', max_length=45, editable=False)
    last_login_attempt = models.DateTimeField(null=True, editable=False)
    last_login_attempt_ip = models.CharField(default='', max_length=45,
                                             editable=False)
    failed_login_attempts = models.PositiveIntegerField(default=0,
                                                        editable=False)
    source = models.PositiveIntegerField(default=amo.LOGIN_SOURCE_UNKNOWN,
                                         editable=False, db_index=True)
    user = models.ForeignKey(DjangoUser, null=True, editable=False, blank=True)
    is_verified = models.BooleanField(default=True)

    class Meta:
        db_table = 'users'

    def __init__(self, *args, **kw):
        super(UserProfile, self).__init__(*args, **kw)
        if self.username:
            self.username = smart_unicode(self.username)

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.display_name or self.username)

    def is_anonymous(self):
        return False

    def get_url_path(self, src=None):
        # TODO: Let users be looked up by slug.
        from amo.utils import urlparams
        return urlparams(reverse('users.profile', args=[self.id]), src=src)

    def flush_urls(self):
        urls = ['*/user/%d/' % self.id,
                self.picture_url,
                ]

        return urls

    @amo.cached_property
    def addons_listed(self):
        """Public add-ons this user is listed as author of."""
        return self.addons.reviewed().exclude(type=amo.ADDON_WEBAPP).filter(
            addonuser__user=self, addonuser__listed=True)

    @amo.cached_property
    def apps_listed(self):
        """Public apps this user is listed as author of."""
        return self.addons.reviewed().filter(type=amo.ADDON_WEBAPP,
            addonuser__user=self, addonuser__listed=True)

    def my_addons(self, n=8):
        """Returns n addons (anything not a webapp)"""
        qs = self.addons.exclude(type=amo.ADDON_WEBAPP)
        qs = order_by_translation(qs, 'name')
        return qs[:n]

    def my_apps(self, n=8):
        """Returns n apps"""
        qs = self.addons.filter(type=amo.ADDON_WEBAPP)
        qs = order_by_translation(qs, 'name')
        return qs[:n]

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
        return self.addonuser_set.exists()

    @amo.cached_property
    def is_app_developer(self):
        return self.addonuser_set.filter(addon__type=amo.ADDON_WEBAPP).exists()

    @amo.cached_property
    def is_artist(self):
        """Is this user a Personas Artist?"""
        return self.addonuser_set.filter(
            addon__type=amo.ADDON_PERSONA).exists()

    @amo.cached_property
    def needs_tougher_password(user):
        if user.source in amo.LOGIN_SOURCE_BROWSERIDS:
            return False
        from access import acl
        return (acl.action_allowed_user(user, 'Admin', '%') or
                acl.action_allowed_user(user, 'Addons', 'Edit') or
                acl.action_allowed_user(user, 'Addons', 'Review') or
                acl.action_allowed_user(user, 'Apps', 'Review') or
                acl.action_allowed_user(user, 'Personas', 'Review') or
                acl.action_allowed_user(user, 'Users', 'Edit'))

    @property
    def name(self):
        return smart_unicode(self.display_name or self.username)

    welcome_name = name

    @property
    def last_login(self):
        """Make UserProfile look more like auth.User."""
        # Django expects this to be non-null, so fake a login attempt.
        if not self.last_login_attempt:
            self.update(last_login_attempt=datetime.now())
        return self.last_login_attempt

    @amo.cached_property
    def reviews(self):
        """All reviews that are not dev replies."""
        return self._reviews_all.filter(reply_to=None)

    def anonymize(self):
        log.info(u"User (%s: <%s>) is being anonymized." % (self, self.email))
        self.email = None
        self.password = "sha512$Anonymous$Password"
        self.username = "Anonymous-%s" % self.id  # Can't be null
        self.display_name = None
        self.homepage = ""
        self.deleted = True
        self.picture_type = ""
        self.save()

    @transaction.commit_on_success
    def restrict(self):
        from amo.utils import send_mail
        log.info(u'User (%s: <%s>) is being restricted and '
                 'its user-generated content removed.' % (self, self.email))
        g = Group.objects.get(rules='Restricted:UGC')
        GroupUser.objects.create(user=self, group=g)
        self.reviews.all().delete()
        self.collections.all().delete()

        t = loader.get_template('users/email/restricted.ltxt')
        send_mail(_('Your account has been restricted'),
                  t.render(Context({})), None, [self.email],
                  use_blacklist=False, real_email=True)

    def unrestrict(self):
        log.info(u'User (%s: <%s>) is being unrestricted.' % (self,
                                                              self.email))
        GroupUser.objects.filter(user=self,
                                 group__rules='Restricted:UGC').delete()

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
        # BrowserID does not store a password.
        if (self.source in amo.LOGIN_SOURCE_BROWSERIDS
            and settings.MARKETPLACE):
            return True

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
        # Can't do CEF logging here because we don't have a request object.

    def email_confirmation_code(self):
        from amo.utils import send_mail
        log.debug("Sending account confirmation code for user (%s)", self)

        url = "%s%s" % (settings.SITE_URL,
                        reverse('users.confirm',
                                args=[self.id, self.confirmationcode]))
        domain = settings.DOMAIN
        t = loader.get_template('users/email/confirm.ltxt')
        c = {'domain': domain, 'url': url, }
        send_mail(_("Please confirm your email address"),
                  t.render(Context(c)), None, [self.email],
                  use_blacklist=False, real_email=True)

    def log_login_attempt(self, successful):
        """Log a user's login attempt"""
        self.last_login_attempt = datetime.now()
        self.last_login_attempt_ip = commonware.log.get_remote_addr()

        if successful:
            log.debug(u"User (%s) logged in successfully" % self)
            self.failed_login_attempts = 0
            self.last_login_ip = commonware.log.get_remote_addr()
        else:
            log.debug(u"User (%s) failed to log in" % self)
            if self.failed_login_attempts < 16777216:
                self.failed_login_attempts += 1

        self.save()

    def create_django_user(self, **kw):
        """Make a django.contrib.auth.User for this UserProfile."""
        # Reusing the id will make our life easier, because we can use the
        # OneToOneField as pk for Profile linked back to the auth.user
        # in the future.
        self.user = DjangoUser(id=self.pk)
        self.user.first_name = ''
        self.user.last_name = ''
        self.user.username = self.username
        self.user.email = self.email
        self.user.password = self.password
        self.user.date_joined = self.created

        for k, v in kw.iteritems():
            setattr(self.user, k, v)

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
        c, new = Collection.objects.get_or_create(
            author=self, type=type_, defaults=defaults)
        if new:
            # Do an extra query to make sure this gets transformed.
            c = Collection.objects.using('default').get(id=c.id)
        return c

    def purchase_ids(self):
        """
        I'm special casing this because we use purchase_ids a lot in the site
        and we are not caching empty querysets in cache-machine.
        That means that when the site is first launched we are having a
        lot of empty queries hit.

        We can probably do this in smarter fashion by making cache-machine
        cache empty queries on an as need basis.
        """
        # Circular import
        from amo.utils import memoize
        from market.models import AddonPurchase

        @memoize(prefix='users:purchase-ids')
        def ids(pk):
            return (AddonPurchase.objects.filter(user=pk)
                                 .values_list('addon_id', flat=True)
                                 .filter(type=amo.CONTRIB_PURCHASE)
                                 .order_by('pk'))
        return ids(self.pk)

    def get_preapproval(self):
        """
        Returns the pre approval object for this user, or None if it does
        not exist
        """
        try:
            return self.preapprovaluser
        except ObjectDoesNotExist:
            pass

    def has_preapproval_key(self):
        """
        Returns the pre approval paypal key for this user, or False if the
        pre_approval doesn't exist or the key is blank.
        """
        return bool(getattr(self.get_preapproval(), 'paypal_key', ''))


@dispatch.receiver(models.signals.post_save, sender=UserProfile,
                   dispatch_uid='user.post_save')
def user_post_save(sender, instance, **kw):
    if not kw.get('raw'):
        from . import tasks
        tasks.index_users.delay([instance.id])


@dispatch.receiver(models.signals.post_delete, sender=UserProfile,
                   dispatch_uid='user.post_delete')
def user_post_delete(sender, instance, **kw):
    if not kw.get('raw'):
        from . import tasks
        tasks.unindex_users.delay([instance.id])


class UserNotification(amo.models.ModelBase):
    user = models.ForeignKey(UserProfile, related_name='notifications')
    notification_id = models.IntegerField()
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'users_notifications'

    @staticmethod
    def update_or_create(update={}, **kwargs):
        rows = UserNotification.objects.filter(**kwargs).update(**update)
        if not rows:
            update.update(dict(**kwargs))
            UserNotification.objects.create(**update)


class RequestUserManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(RequestUserManager, self).get_query_set()
        return qs.transform(RequestUser.transformer)


class RequestUser(UserProfile):
    """
    A RequestUser has extra attributes we don't care about for normal users.
    """

    objects = RequestUserManager()

    def __init__(self, *args, **kw):
        super(RequestUser, self).__init__(*args, **kw)
        self.mobile_addons = []
        self.favorite_addons = []
        self.watching = []

    class Meta:
        proxy = True

    @staticmethod
    def transformer(users):
        # We don't want to cache these things on every UserProfile; they're
        # only used by a user attached to a request.
        if not users:
            return

        # Touch this @cached_property so the answer is cached with the object.
        user = users[0]
        user.is_developer

        # Until the Marketplace gets collections, these lookups are pointless.
        if settings.MARKETPLACE:
            return

        from bandwagon.models import CollectionAddon, CollectionWatcher
        SPECIAL = amo.COLLECTION_SPECIAL_SLUGS.keys()
        qs = CollectionAddon.objects.filter(
            collection__author=user, collection__type__in=SPECIAL)
        addons = dict((type_, []) for type_ in SPECIAL)
        for addon, ctype in qs.values_list('addon', 'collection__type'):
            addons[ctype].append(addon)
        user.mobile_addons = addons[amo.COLLECTION_MOBILE]
        user.favorite_addons = addons[amo.COLLECTION_FAVORITES]
        user.watching = list((CollectionWatcher.objects.filter(user=user)
                             .values_list('collection', flat=True)))

    def _cache_keys(self):
        # Add UserProfile.cache_key so RequestUser gets invalidated when the
        # UserProfile is changed.
        keys = super(RequestUser, self)._cache_keys()
        return keys + (UserProfile(id=self.id).cache_key,)


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
        qs = cls.objects.all()
        f = lambda: [u.lower() for u in qs.values_list('username', flat=True)]
        blacklist = caching.cached_with(qs, f, 'blocked')
        return username.lower() in blacklist


class BlacklistedEmailDomain(amo.models.ModelBase):
    """Blacklisted user e-mail domains."""
    domain = models.CharField(max_length=255, unique=True, default='',
                              blank=False)

    def __unicode__(self):
        return self.domain

    @classmethod
    def blocked(cls, domain):
        qs = cls.objects.all()
        f = lambda: list(qs.values_list('domain', flat=True))
        blacklist = caching.cached_with(qs, f, 'blocked')
        # because there isn't a good way to know if the domain is
        # "example.com" or "example.co.jp", we'll re-construct it...
        # so if it's "bad.example.co.jp", the following check the
        # values in ['bad.example.co.jp', 'example.co.jp', 'co.jp']
        x = domain.lower().split('.')
        for d in ['.'.join(x[y:]) for y in range(len(x) - 1)]:
            if d in blacklist:
                return True


class BlacklistedPassword(amo.models.ModelBase):
    """Blacklisted passwords"""
    password = models.CharField(max_length=255, unique=True, blank=False)

    def __unicode__(self):
        return self.password

    @classmethod
    def blocked(cls, password):
        return cls.objects.filter(password=password)


class UserHistory(amo.models.ModelBase):
    email = models.EmailField()
    user = models.ForeignKey(UserProfile, related_name='history')

    class Meta:
        db_table = 'users_history'
        ordering = ('-created',)


@UserProfile.on_change
def watch_email(old_attr={}, new_attr={}, instance=None,
                sender=None, **kw):
    new_email, old_email = new_attr.get('email'), old_attr.get('email')
    if old_email and new_email != old_email:
        log.debug('Creating user history for user: %s' % instance.pk)
        UserHistory.objects.create(email=old_email, user_id=instance.pk)
