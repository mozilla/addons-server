import os
import random
import re
import time
from datetime import datetime

from django import forms
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core import validators
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.translation import ugettext
from django.utils.encoding import force_text
from django.utils.functional import cached_property, lazy

import caching.base as caching
import waffle
from waffle.models import Switch

import olympia.core.logger
from olympia import amo, core
from olympia.amo.models import OnChangeMixin, ManagerBase, ModelBase
from olympia.access.models import Group, GroupUser
from olympia.amo.urlresolvers import reverse
from olympia.translations.query import order_by_translation
from olympia.users.notifications import NOTIFICATIONS_BY_ID

log = olympia.core.logger.getLogger('z.users')


def generate_auth_id():
    """Generate a random integer to be used when generating API auth tokens."""
    # We use MySQL's maximum value for an unsigned int:
    # https://dev.mysql.com/doc/refman/5.7/en/integer-types.html
    return random.SystemRandom().randint(1, 4294967295)


class UserForeignKey(models.ForeignKey):
    """
    A replacement for  models.ForeignKey('users.UserProfile').

    This field uses UserEmailField to make form fields key off the user's email
    instead of the primary key id.  We also hook up autocomplete automatically.
    """

    def __init__(self, *args, **kwargs):
        # "to" is passed here from the migration framework; we ignore it
        # since it's the same for every instance.
        kwargs.pop('to', None)
        self.to = 'users.UserProfile'
        super(UserForeignKey, self).__init__(self.to, *args, **kwargs)

    def value_from_object(self, obj):
        return getattr(obj, self.name).email

    def deconstruct(self):
        name, path, args, kwargs = super(UserForeignKey, self).deconstruct()
        kwargs['to'] = self.to
        return (name, path, args, kwargs)

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
            raise forms.ValidationError(ugettext('No user with that email.'))

    def widget_attrs(self, widget):
        lazy_reverse = lazy(reverse, str)
        return {'class': 'email-autocomplete',
                'data-src': lazy_reverse('users.ajax')}


class UserManager(BaseUserManager, ManagerBase):

    def create_user(self, username, email, fxa_id=None):
        # We'll send username=None when registering through FxA to generate
        # an anonymous username.
        now = timezone.now()
        user = self.model(
            username=username, email=email, fxa_id=fxa_id,
            last_login=now)
        if username is None:
            user.anonymize_username()
        log.debug('Creating user with email {} and username {}'.format(
            email, username))
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email):
        """
        Creates and saves a superuser.
        """
        user = self.create_user(username, email)
        admins = Group.objects.get(name='Admins')
        GroupUser.objects.create(user=user, group=admins)
        return user


class UserProfile(OnChangeMixin, ModelBase, AbstractBaseUser):
    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']
    username = models.CharField(max_length=255, default='', unique=True)
    display_name = models.CharField(max_length=255, default='', null=True,
                                    blank=True)

    email = models.EmailField(unique=True, null=True, max_length=75)

    averagerating = models.CharField(max_length=255, blank=True, null=True)
    # biography can (and does) contains html and other unsanitized content.
    # It must be cleaned before display.
    biography = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    display_collections_fav = models.BooleanField(default=False)
    homepage = models.URLField(max_length=255, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, null=True)
    notifycompat = models.BooleanField(default=True)
    notifyevents = models.BooleanField(default=True)
    occupation = models.CharField(max_length=255, default='', blank=True)
    # This is essentially a "has_picture" flag right now
    picture_type = models.CharField(max_length=75, default='', blank=True)
    read_dev_agreement = models.DateTimeField(null=True, blank=True)

    last_login_ip = models.CharField(default='', max_length=45, editable=False)
    last_login_attempt = models.DateTimeField(null=True, editable=False)
    last_login_attempt_ip = models.CharField(default='', max_length=45,
                                             editable=False)
    failed_login_attempts = models.PositiveIntegerField(default=0,
                                                        editable=False)

    is_verified = models.BooleanField(default=True)

    fxa_id = models.CharField(blank=True, null=True, max_length=128)

    # Identifier that is used to invalidate internal API tokens (i.e. those
    # that we generate for addons-frontend, NOT the API keys external clients
    # use) and django sessions. Should be changed if a user is known to have
    # been compromised.
    auth_id = models.PositiveIntegerField(null=True, default=generate_auth_id)

    class Meta:
        db_table = 'users'

    def __init__(self, *args, **kw):
        super(UserProfile, self).__init__(*args, **kw)
        if self.username:
            self.username = force_text(self.username)

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.display_name or self.username)

    @property
    def is_superuser(self):
        return self.groups.filter(rules='*:*').exists()

    @property
    def is_staff(self):
        from olympia.access import acl
        return acl.action_allowed_user(self, amo.permissions.ADMIN)

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser

    def has_read_developer_agreement(self):
        if self.read_dev_agreement is None:
            return False
        if waffle.switch_is_active('post-review'):
            # We want to make sure developers read the latest version of the
            # agreement. The cutover date is the date the switch was last
            # modified to turn it on. (When removing the waffle, change this
            # for a static date).
            switch = Switch.objects.get(name='post-review')
            return self.read_dev_agreement > switch.modified
        return True

    backend = 'django.contrib.auth.backends.ModelBackend'

    def get_session_auth_hash(self):
        """Return a hash used to invalidate sessions of users when necessary.

        Can return None if auth_id is not set on this user."""
        if self.auth_id is None:
            # Old user that has not re-logged since we introduced that field,
            # return None, it won't be used by django session invalidation
            # mechanism.
            return None
        # Mimic what the AbstractBaseUser implementation does, but with our
        # own custom field instead of password, which we don't have.
        key_salt = 'olympia.models.users.UserProfile.get_session_auth_hash'
        return salted_hmac(key_salt, str(self.auth_id)).hexdigest()

    @staticmethod
    def create_user_url(id_, username=None, url_name='profile', src=None,
                        args=None):
        """
        We use <username> as the slug, unless it contains gross
        characters - in which case use <id> as the slug.
        """
        from olympia.amo.utils import urlparams
        chars = '/<>"\''
        if not username or any(x in chars for x in username):
            username = id_
        args = args or []
        url = reverse('users.%s' % url_name, args=[username] + args)
        return urlparams(url, src=src)

    def get_themes_url_path(self, src=None, args=None):
        return self.create_user_url(self.id, self.username, 'themes', src=src,
                                    args=args)

    def get_url_path(self, src=None):
        return self.create_user_url(self.id, self.username, 'profile', src=src)

    @cached_property
    def groups_list(self):
        """List of all groups the user is a member of, as a cached property."""
        return list(self.groups.all())

    @property
    def num_addons_listed(self):
        """Number of public add-ons this user is listed as author of."""
        return self.addons.public().filter(
            addonuser__user=self, addonuser__listed=True).count()

    def my_addons(self, n=8):
        """Returns n addons"""
        qs = order_by_translation(self.addons, 'name')
        return qs[:n]

    @property
    def picture_dir(self):
        from olympia.amo.templatetags.jinja_helpers import user_media_path
        split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(self.id))
        return os.path.join(user_media_path('userpics'),
                            split_id.group(2) or '0',
                            split_id.group(1) or '0')

    @property
    def picture_path(self):
        return os.path.join(self.picture_dir, str(self.id) + '.png')

    @property
    def picture_url(self):
        from olympia.amo.templatetags.jinja_helpers import user_media_url
        if not self.picture_type:
            return settings.STATIC_URL + '/img/zamboni/anon_user.png'
        else:
            split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(self.id))
            modified = int(time.mktime(self.modified.timetuple()))
            path = "/".join([
                split_id.group(2) or '0',
                split_id.group(1) or '0',
                "%s.png?modified=%s" % (self.id, modified)
            ])
            return user_media_url('userpics') + path

    @cached_property
    def is_developer(self):
        return self.addonuser_set.exclude(
            addon__status=amo.STATUS_DELETED).exists()

    @cached_property
    def is_addon_developer(self):
        return self.addonuser_set.exclude(
            addon__type=amo.ADDON_PERSONA).exists()

    @cached_property
    def is_artist(self):
        """Is this user a Personas Artist?"""
        return self.addonuser_set.filter(
            addon__type=amo.ADDON_PERSONA).exists()

    @property
    def name(self):
        if self.display_name:
            return force_text(self.display_name)
        elif self.has_anonymous_username():
            # L10n: {id} will be something like "13ad6a", just a random number
            # to differentiate this user from other anonymous users.
            return ugettext('Anonymous user {id}').format(
                id=self._anonymous_username_id())
        else:
            return force_text(self.username)

    welcome_name = name

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.username

    def _anonymous_username_id(self):
        if self.has_anonymous_username():
            return self.username.split('-')[1][:6]

    def anonymize_username(self):
        """Set an anonymous username."""
        if self.pk:
            log.info('Anonymizing username for {}'.format(self.pk))
        else:
            log.info('Generating username for {}'.format(self.email))
        self.username = 'anonymous-{}'.format(os.urandom(16).encode('hex'))
        return self.username

    def has_anonymous_username(self):
        return re.match('^anonymous-[0-9a-f]{32}$', self.username)

    def has_anonymous_display_name(self):
        return not self.display_name and self.has_anonymous_username()

    @cached_property
    def reviews(self):
        """All reviews that are not dev replies."""
        qs = self._reviews_all.filter(reply_to=None)
        # Force the query to occur immediately. Several
        # reviews-related tests hang if this isn't done.
        return qs

    def delete(self, hard=False):
        if hard:
            super(UserProfile, self).delete()
        else:
            log.info(
                u'User (%s: <%s>) is being anonymized.' % (self, self.email))
            self.email = None
            self.fxa_id = None
            self.username = "Anonymous-%s" % self.id  # Can't be null
            self.display_name = None
            self.homepage = ""
            self.deleted = True
            self.picture_type = ""
            self.save()

    def set_unusable_password(self):
        raise NotImplementedError('cannot set unusable password')

    def set_password(self, password):
        raise NotImplementedError('cannot set password')

    def check_password(self, password):
        raise NotImplementedError('cannot check password')

    def log_login_attempt(self, successful):
        """Log a user's login attempt"""
        self.last_login_attempt = datetime.now()
        self.last_login_attempt_ip = core.get_remote_addr()

        if successful:
            log.debug(u"User (%s) logged in successfully" % self)
            self.failed_login_attempts = 0
            self.last_login_ip = core.get_remote_addr()
        else:
            log.debug(u"User (%s) failed to log in" % self)
            if self.failed_login_attempts < 16777216:
                self.failed_login_attempts += 1

        self.save(update_fields=['last_login_ip', 'last_login_attempt',
                                 'last_login_attempt_ip',
                                 'failed_login_attempts'])

    def mobile_collection(self):
        return self.special_collection(
            amo.COLLECTION_MOBILE,
            defaults={'slug': 'mobile', 'listed': False,
                      'name': ugettext('My Mobile Add-ons')})

    def favorites_collection(self):
        return self.special_collection(
            amo.COLLECTION_FAVORITES,
            defaults={'slug': 'favorites', 'listed': False,
                      'name': ugettext('My Favorite Add-ons')})

    def special_collection(self, type_, defaults):
        from olympia.bandwagon.models import Collection
        c, new = Collection.objects.get_or_create(
            author=self, type=type_, defaults=defaults)
        if new:
            # Do an extra query to make sure this gets transformed.
            c = Collection.objects.using('default').get(id=c.id)
        return c

    def addons_for_collection_type(self, type_):
        """Return the addons for the given special collection type."""
        from olympia.bandwagon.models import CollectionAddon
        qs = CollectionAddon.objects.filter(
            collection__author=self, collection__type=type_)
        return qs.values_list('addon', flat=True)

    @cached_property
    def mobile_addons(self):
        return self.addons_for_collection_type(amo.COLLECTION_MOBILE)

    @cached_property
    def favorite_addons(self):
        return self.addons_for_collection_type(amo.COLLECTION_FAVORITES)

    @cached_property
    def watching(self):
        return self.collectionwatcher_set.values_list('collection', flat=True)


class UserNotification(ModelBase):
    user = models.ForeignKey(UserProfile, related_name='notifications')
    notification_id = models.IntegerField()
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'users_notifications'

    @property
    def notification(self):
        return NOTIFICATIONS_BY_ID[self.notification_id]


class DeniedName(ModelBase):
    """Denied User usernames and display_names + Collections' names."""
    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'users_denied_name'

    def __unicode__(self):
        return self.name

    @classmethod
    def blocked(cls, name):
        """
        Check to see if a given name is in the (cached) deny list.
        Return True if the name contains one of the denied terms.

        """
        name = name.lower()
        qs = cls.objects.all()

        def f():
            return [n.lower() for n in qs.values_list('name', flat=True)]

        blocked_list = caching.cached_with(qs, f, 'blocked')
        return any(n in name for n in blocked_list)


class UserHistory(ModelBase):
    email = models.EmailField(max_length=75)
    user = models.ForeignKey(UserProfile, related_name='history')

    class Meta:
        db_table = 'users_history'
        ordering = ('-created',)


@UserProfile.on_change
def watch_email(old_attr=None, new_attr=None, instance=None,
                sender=None, **kw):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    new_email, old_email = new_attr.get('email'), old_attr.get('email')
    if old_email and new_email != old_email:
        log.debug('Creating user history for user: %s' % instance.pk)
        UserHistory.objects.create(email=old_email, user_id=instance.pk)
