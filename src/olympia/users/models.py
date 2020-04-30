import binascii
import os
import random
import re
import time
import ipaddress
from urllib.parse import urljoin

from fnmatch import fnmatchcase
from datetime import datetime
import requests

from django import forms
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.auth.signals import user_logged_in
from django.core import validators
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_text
from django.utils.functional import cached_property
from django.utils.translation import ugettext, ugettext_lazy as _

import olympia.core.logger

from olympia import amo, core
from olympia.access.models import Group, GroupUser
from olympia.amo.decorators import use_primary_db
from olympia.amo.fields import PositiveAutoField, CIDRField
from olympia.amo.models import ManagerBase, ModelBase, OnChangeMixin
from olympia.amo.urlresolvers import reverse
from olympia.amo.validators import OneOrMorePrintableCharacterValidator
from olympia.translations.query import order_by_translation
from olympia.users.notifications import NOTIFICATIONS_BY_ID


log = olympia.core.logger.getLogger('z.users')


def generate_auth_id():
    """Generate a random integer to be used when generating API auth tokens."""
    # We use MySQL's maximum value for an unsigned int:
    # https://dev.mysql.com/doc/refman/5.7/en/integer-types.html
    return random.SystemRandom().randint(1, 4294967295)


class UserEmailField(forms.ModelChoiceField):
    """
    Field to use for ForeignKeys to UserProfile, to use email instead of pk.
    Requires the form to set the email value in the initial data instead of the
    pk.

    Displays disabled state as readonly thanks to UserEmailBoundField.
    """
    default_error_messages = {
        'invalid_choice': ugettext('No user with that email.')
    }
    widget = forms.EmailInput

    def __init__(self, *args, **kwargs):
        if kwargs.get('to_field_name') is None:
            kwargs['to_field_name'] = 'email'
        super().__init__(*args, **kwargs)

    def limit_choices_to(self):
        return {'deleted': False}

    def widget_attrs(self, widget):
        return {'class': 'author-email'}

    def get_bound_field(self, form, field_name):
        return UserEmailBoundField(form, self, field_name)


class UserEmailBoundField(forms.BoundField):
    """A BoundField that treats disabled as readonly (enabling users to select
    the text, not suffer from low contrast etc. The form field underneath
    behaves normally and django will still ignore incoming data for it)."""

    def build_widget_attrs(self, *args, **kwargs):
        attrs = super().build_widget_attrs(*args, **kwargs)
        if attrs.get('disabled'):
            attrs.pop('disabled')
            attrs['readonly'] = True
        return attrs


class UserManager(BaseUserManager, ManagerBase):

    def create_user(self, username, email, fxa_id=None, **kwargs):
        # We'll send username=None when registering through FxA to generate
        # an anonymous username.
        now = timezone.now()
        user = self.model(
            username=username,
            email=email,
            fxa_id=fxa_id,
            last_login=now,
            **kwargs
        )
        if username is None:
            user.anonymize_username()
        log.debug('Creating user with email {} and username {}'.format(
            email, username))
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, fxa_id=None):
        """
        Creates and saves a superuser.
        """
        user = self.create_user(username=username, email=email, fxa_id=fxa_id)
        admins = Group.objects.get(name='Admins')
        GroupUser.objects.create(user=user, group=admins)
        return user


class UserProfile(OnChangeMixin, ModelBase, AbstractBaseUser):
    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']
    username = models.CharField(max_length=255, default='', unique=True)
    display_name = models.CharField(
        max_length=50, default='', null=True, blank=True,
        validators=[validators.MinLengthValidator(2),
                    OneOrMorePrintableCharacterValidator()])

    email = models.EmailField(unique=True, null=True, max_length=75)

    averagerating = models.FloatField(null=True)
    # biography can (and does) contain html and other unsanitized content.
    # It must be cleaned before display.
    biography = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    homepage = models.URLField(max_length=255, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, null=True)
    occupation = models.CharField(max_length=255, default='', blank=True)
    # This is essentially a "has_picture" flag right now
    picture_type = models.CharField(max_length=75, default=None, null=True,
                                    blank=True)
    read_dev_agreement = models.DateTimeField(null=True, blank=True)

    last_login_ip = models.CharField(default='', max_length=45, editable=False)
    email_changed = models.DateTimeField(null=True, editable=False)
    banned = models.DateTimeField(null=True, editable=False)

    # Is the profile page for this account publicly viewable?
    # Note: this is only used for API responses (thus addons-frontend) - all
    # users's profile pages are publicly viewable on legacy frontend.
    # TODO: Remove this note once legacy profile pages are removed.
    is_public = models.BooleanField(default=False, db_column='public')

    fxa_id = models.CharField(blank=True, null=True, max_length=128)

    # Identifier that is used to invalidate internal API tokens (i.e. those
    # that we generate for addons-frontend, NOT the API keys external clients
    # use) and django sessions. Should be changed if a user is known to have
    # been compromised.
    auth_id = models.PositiveIntegerField(null=True, default=generate_auth_id)

    # Token used to manage the users subscriptions in basket. Basket
    # is proxying directly to Salesforce, e.g for the about-addons
    # newsletter
    basket_token = models.CharField(blank=True, default='', max_length=128)

    bypass_upload_restrictions = models.BooleanField(default=False)

    reviewer_name = models.CharField(
        max_length=50, default='', null=True, blank=True,
        validators=[validators.MinLengthValidator(2)])

    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=('created',), name='created'),
            models.Index(fields=('fxa_id',), name='users_fxa_id_index'),
        ]

    def __init__(self, *args, **kw):
        super(UserProfile, self).__init__(*args, **kw)
        if self.username:
            self.username = force_text(self.username)

    def __str__(self):
        return u'%s: %s' % (self.id, self.display_name or self.username)

    @property
    def is_superuser(self):
        return any(group.rules == '*:*' for group in self.groups_list)

    @property
    def is_staff(self):
        """Property indicating whether the user should be able to log in to
        the django admin tools. Does not guarantee that the user will then
        be able to do anything, as each module can have its own permission
        checks. (see has_module_perms() and has_perm())"""
        from olympia.access import acl
        return acl.action_allowed_user(self, amo.permissions.ANY_ADMIN)

    def has_perm(self, perm, obj=None):
        """Determine what the user can do in the django admin tools.

        perm is in the form "<app>.<action>_<model>".
        """
        from olympia.access import acl
        return acl.action_allowed_user(
            self, amo.permissions.DJANGO_PERMISSIONS_MAPPING[perm])

    def has_module_perms(self, app_label):
        """Determine whether the user can see a particular app in the django
        admin tools. """
        # If the user is a superuser or has permission for any action available
        # for any of the models of the app, they can see the app in the django
        # admin. The is_superuser check is needed to allow superuser to access
        # modules that are not in the mapping at all (i.e. things only they
        # can access).
        return (self.is_superuser or
                any(self.has_perm(key)
                    for key in amo.permissions.DJANGO_PERMISSIONS_MAPPING
                    if key.startswith('%s.' % app_label)))

    def has_read_developer_agreement(self):
        from olympia.zadmin.models import get_config

        if self.read_dev_agreement is None:
            return False
        try:
            last_agreement_change_config = get_config(
                'last_dev_agreement_change_date')
            change_config_date = datetime.strptime(
                last_agreement_change_config, '%Y-%m-%d %H:%M')

            # If the config date is in the future, instead check against the
            # fallback date
            if change_config_date > datetime.now():
                return (self.read_dev_agreement >
                        settings.DEV_AGREEMENT_CHANGE_FALLBACK)

            return self.read_dev_agreement > change_config_date
        except (ValueError, TypeError):
            log.exception('last_developer_agreement_change misconfigured, '
                          '"%s" is not a '
                          'datetime' % last_agreement_change_config)
            return (self.read_dev_agreement >
                    settings.DEV_AGREEMENT_CHANGE_FALLBACK)

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
    def create_user_url(id_, src=None):
        from olympia.amo.utils import urlparams
        url = reverse('users.profile', args=[id_])
        return urlparams(url, src=src)

    def get_themes_url_path(self, src=None, args=None):
        from olympia.amo.utils import urlparams
        url = reverse('users.themes', args=[self.id] + (args or []))
        return urlparams(url, src=src)

    def get_url_path(self, src=None):
        return self.create_user_url(self.id, src=src)

    @cached_property
    def groups_list(self):
        """List of all groups the user is a member of, as a cached property."""
        return list(self.groups.all())

    def get_addons_listed(self):
        """Return queryset of public add-ons thi user is listed as author of.
        """
        return self.addons.public().filter(
            addonuser__user=self, addonuser__listed=True)

    @property
    def num_addons_listed(self):
        """Number of public add-ons this user is listed as author of."""
        return self.get_addons_listed().count()

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
    def picture_path_original(self):
        return os.path.join(self.picture_dir, str(self.id) + '_original.png')

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
    def cached_developer_status(self):
        addon_types = list(
            self.addonuser_set
            .exclude(addon__status=amo.STATUS_DELETED)
            .values_list('addon__type', flat=True))

        all_themes = [t for t in addon_types if t in amo.GROUP_TYPE_THEME]
        return {
            'is_developer': bool(addon_types),
            'is_extension_developer': len(all_themes) != len(addon_types),
            'is_theme_developer': bool(all_themes)
        }

    @property
    def is_developer(self):
        return self.cached_developer_status['is_developer']

    @property
    def is_addon_developer(self):
        return self.cached_developer_status['is_extension_developer']

    @property
    def is_artist(self):
        """Is this user a theme artist?"""
        return self.cached_developer_status['is_theme_developer']

    @use_primary_db
    def update_is_public(self):
        pre = self.is_public
        is_public = (
            self.addonuser_set.filter(
                role__in=[amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV],
                listed=True,
                addon__status=amo.STATUS_APPROVED).exists())
        if is_public != pre:
            log.info('Updating %s.is_public from %s to %s' % (
                self.pk, pre, is_public))
            self.update(is_public=is_public)
        else:
            log.info('Not changing %s.is_public from %s' % (self.pk, pre))

    @property
    def name(self):
        if self.display_name:
            return force_text(self.display_name)
        else:
            return ugettext('Firefox user {id}').format(id=self.id)

    welcome_name = name

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name

    def anonymize_username(self):
        """Set an anonymous username."""
        if self.pk:
            log.info('Anonymizing username for {}'.format(self.pk))
        else:
            log.info('Generating username for {}'.format(self.email))
        self.username = 'anonymous-{}'.format(
            force_text(binascii.b2a_hex(os.urandom(16))))
        return self.username

    @property
    def has_anonymous_username(self):
        return re.match('^anonymous-[0-9a-f]{32}$', self.username) is not None

    @property
    def has_anonymous_display_name(self):
        return not self.display_name

    @cached_property
    def ratings(self):
        """All ratings that are not dev replies."""
        return self._ratings_all.filter(reply_to=None)

    def delete_or_disable_related_content(self, delete=False):
        """Delete or disable content produced by this user if they are the only
        author."""
        self.collections.all().delete()
        for addon in self.addons.all().iterator():
            if not addon.authors.exclude(pk=self.pk).exists():
                if delete:
                    addon.delete()
                else:
                    addon.force_disable()
            else:
                addon.addonuser_set.filter(user=self).delete()
        user_responsible = core.get_user()
        self._ratings_all.all().delete(user_responsible=user_responsible)
        self.delete_picture()

    def delete_picture(self, picture_path=None, original_picture_path=None):
        """Delete picture of this user."""
        # Recursive import
        from olympia.users.tasks import delete_photo

        if picture_path is None:
            picture_path = self.picture_path
        if original_picture_path is None:
            original_picture_path = self.picture_path_original

        if storage.exists(picture_path):
            delete_photo.delay(picture_path)

        if storage.exists(original_picture_path):
            delete_photo.delay(original_picture_path)

        if self.picture_type:
            self.update(picture_type=None)

    def ban_and_disable_related_content(self):
        """Admin method to ban the user and disable the content they produced.

        Similar to deletion, except that the content produced by the user is
        forcibly disabled instead of being deleted where possible, and the user
        is not fully anonymized: we keep their fxa_id and email so that they
        are never able to log back in.
        """
        self.delete_or_disable_related_content(delete=False)
        return self.delete(ban_user=True)

    @classmethod
    def ban_and_disable_related_content_bulk(cls, users, move_files=False):
        """Like ban_and_disable_related_content, but in bulk. """
        from olympia.addons.models import Addon, AddonUser
        from olympia.addons.tasks import index_addons
        from olympia.bandwagon.models import Collection
        from olympia.files.models import File
        from olympia.ratings.models import Rating

        # collect affected addons
        addon_ids = set(
            Addon.unfiltered.exclude(status=amo.STATUS_DELETED)
            .filter(addonuser__user__in=users).values_list('id', flat=True))

        # First addons who have other authors we aren't banning
        addon_joint_ids = set(
            AddonUser.objects.filter(addon_id__in=addon_ids)
            .exclude(user__in=users).values_list('addon_id', flat=True))
        AddonUser.objects.filter(
            user__in=users, addon_id__in=addon_joint_ids).delete()

        # Then deal with users who are the sole author
        addons_sole = Addon.unfiltered.filter(
            id__in=addon_ids - addon_joint_ids)
        # set the status to disabled - using the manager update() method
        addons_sole.update(status=amo.STATUS_DISABLED)
        # collect Files that need to be disabled now the addons are disabled
        files_to_disable = File.objects.filter(version__addon__in=addons_sole)
        files_to_disable.update(status=amo.STATUS_DISABLED)
        if move_files:
            # if necessary move the files out of the CDN (expensive operation)
            for file_ in files_to_disable:
                file_.hide_disabled_file()

        # Finally run Addon.force_disable to add the logging; update versions
        # Status was already DISABLED so shouldn't fire watch_disabled again.
        for addon in addons_sole:
            addon.force_disable()
        # Don't pass a set to a .delay - sets can't be serialized as JSON
        index_addons.delay(list(addon_ids - addon_joint_ids))

        # delete the other content associated with the user
        Collection.objects.filter(author__in=users).delete()
        Rating.objects.filter(user__in=users).delete(
            user_responsible=core.get_user())
        # And then delete the users.
        for user in users:
            user.delete(ban_user=True)

    def delete(self, hard=False, ban_user=False):
        # Cache the values in case we do a hard delete and loose
        # reference to the user-id.
        picture_path = self.picture_path
        original_picture_path = self.picture_path_original

        if hard:
            super(UserProfile, self).delete()
        else:
            if ban_user:
                log.info(
                    f'User ({self}: <{self.email}>) is being partially '
                    'anonymized and banned.')
                # We don't clear email or fxa_id when banning
                self.banned = datetime.now()
            else:
                log.info(u'User (%s: <%s>) is being anonymized.' % (
                    self, self.email))
                self.email = None
                self.fxa_id = None
            # last_login_ip is kept, deleted by clear_old_last_login_ip
            # command after 6 months.
            self.biography = ''
            self.display_name = None
            self.homepage = ''
            self.location = ''
            self.deleted = True
            self.picture_type = None
            self.auth_id = generate_auth_id()
            self.anonymize_username()
            self.save()

        self.delete_picture(picture_path=picture_path,
                            original_picture_path=original_picture_path)

    def set_unusable_password(self):
        raise NotImplementedError('cannot set unusable password')

    def set_password(self, password):
        raise NotImplementedError('cannot set password')

    def check_password(self, password):
        raise NotImplementedError('cannot check password')

    @staticmethod
    def user_logged_in(sender, request, user, **kwargs):
        """Log when a user logs in and records its IP address."""
        log.debug(u'User (%s) logged in successfully' % user,
                  extra={'email': user.email})
        user.update(last_login_ip=core.get_remote_addr() or '')

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
    user = models.ForeignKey(
        UserProfile, related_name='notifications', on_delete=models.CASCADE)
    notification_id = models.IntegerField()
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'users_notifications'
        indexes = [
            models.Index(fields=('user',), name='user_id'),
        ]

    @property
    def notification(self):
        return NOTIFICATIONS_BY_ID.get(self.notification_id)

    def __str__(self):
        return (
            u'{user}, {notification}, enabled={enabled}'
            .format(
                user=self.user.name,
                notification=self.notification.short,
                enabled=self.enabled))


class DeniedName(ModelBase):
    """Denied User usernames and display_names + Collections' names."""
    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'users_denied_name'

    def __str__(self):
        return self.name

    @classmethod
    def blocked(cls, name):
        """
        Check to see if a given name is in the (cached) deny list.
        Return True if the name contains one of the denied terms.

        """
        name = name.lower()
        qs = cls.objects.all()

        def fetch_names():
            return [n.lower() for n in qs.values_list('name', flat=True)]

        blocked_list = cache.get_or_set('denied-name:blocked', fetch_names)
        return any(n in name for n in blocked_list)


class GetErrorMessageMixin():

    @classmethod
    def get_error_message(cls, is_api):
        return cls.error_message


class IPNetworkUserRestriction(GetErrorMessageMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    network = CIDRField(
        blank=True, null=True,
        help_text=_(
            'Enter a valid IPv6 or IPv6 CIDR network range, eg. 127.0.0.1/28'))

    error_message = _('Multiple add-ons violating our policies have been'
                      ' submitted from your location. The IP address has been'
                      ' blocked.')

    class Meta:
        db_table = 'users_user_network_restriction'

    def __str__(self):
        return str(self.network)

    @classmethod
    def allow_request(cls, request):
        """
        Return whether the specified request should be allowed to submit
        add-ons.
        """
        try:
            remote_addr = ipaddress.ip_address(request.META.get('REMOTE_ADDR'))
            if request.user:
                user_last_login_ip = ipaddress.ip_address(
                    request.user.last_login_ip)
        except ValueError:
            # If we don't have a valid ip address, let's deny
            return False

        restrictions = IPNetworkUserRestriction.objects.all()

        for restriction in restrictions:
            if (remote_addr in restriction.network or
                    user_last_login_ip in restriction.network):
                log.info('Restricting request from %s %s, %s %s (%s)',
                         'ip', remote_addr,
                         'last_login_ip', user_last_login_ip,
                         'network=%s' % restriction.network)
                return False

        return True


class NormalizeEmailMixin:
    @classmethod
    def normalize_email(cls, email):
        """
        Normalize email by removing any dots and removing anything after the
        first '+' in the local part.
        """
        local_part, _, domain = email.rpartition('@')
        local_part = local_part.partition('+')[0].replace('.', '')
        normalized_email = '%s@%s' % (local_part, domain)
        if normalized_email != email:
            log.info('Normalized email from %s to %s', email, normalized_email)
        return normalized_email


class EmailUserRestriction(
        GetErrorMessageMixin, NormalizeEmailMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    email_pattern = models.CharField(
        _('Email Pattern'),
        max_length=100,
        help_text=_(
            'Either enter full domain or email that should be blocked or use '
            ' glob-style wildcards to match other patterns.'
            ' E.g "@*.mail.com"\n'
            ' Please note that we do not include "@" in the match so you '
            ' should do that in the pattern.'))

    error_message = _('The email address used for your account is not '
                      'allowed for add-on submission.')

    class Meta:
        db_table = 'users_user_email_restriction'

    def __str__(self):
        return str(self.email_pattern)

    @classmethod
    def allow_request(cls, request):
        """
        Return whether the specified request should be allowed to submit
        add-ons.
        """
        if not request.user.is_authenticated:
            return False

        return cls.allow_email(cls.normalize_email(request.user.email))

    @classmethod
    def allow_email(cls, email):
        """
        Return whether the specified email should be allowed to submit add-ons.
        """
        restrictions = EmailUserRestriction.objects.all()

        for restriction in restrictions:
            if fnmatchcase(email, restriction.email_pattern):
                log.info('Restricting request from %s %s (%s)',
                         'email', email,
                         'email_pattern=%s' % restriction.email_pattern)
                return False

        return True


class DisposableEmailDomainRestriction(GetErrorMessageMixin, ModelBase):
    domain = models.CharField(
        unique=True,
        max_length=255,
        help_text=_('Enter full disposable email domain that should be '
                    'blocked. Wildcards are not supported: if you need those, '
                    'or need to match against the entire email and not just '
                    'the domain part, use "Email user restrictions" instead.'))

    error_message = EmailUserRestriction.error_message

    class Meta:
        db_table = 'users_disposable_email_domain_restriction'

    def __str__(self):
        return str(self.domain)

    @classmethod
    def allow_request(cls, request):
        """
        Return whether the specified request should be allowed to submit
        add-ons.
        """
        if not request.user.is_authenticated:
            return False

        email_domain = request.user.email.rsplit('@', maxsplit=1)[-1]

        # Unlike EmailUserRestriction we can use .exists() directly. This
        # allows us to have thousands of entries without perf issues.
        return not cls.objects.filter(domain=email_domain).exists()


class ReputationRestrictionMixin:
    reputation_threshold = 50

    @classmethod
    def allow_reputation(cls, reputation_type, target):
        """
        Call reputation service for a given `reputation_type` and `target`,
        returning whether or not it should be allowed.

        `reputation_type` is either "email" or "ip", and `target` is either the
        email or ip address from the request we want to check.

        Needs REPUTATION_SERVICE_URL, REPUTATION_SERVICE_TOKEN and
        REPUTATION_SERVICE_TIMEOUT settings set, otherwise it will always
        return True.
        """
        if (not settings.REPUTATION_SERVICE_URL or
                not settings.REPUTATION_SERVICE_TOKEN or
                settings.REPUTATION_SERVICE_TIMEOUT is None):
            return True  # Not configured.
        url = urljoin(
            settings.REPUTATION_SERVICE_URL,
            f'/type/{reputation_type}/{target}'
        )
        response = requests.get(
            url, timeout=settings.REPUTATION_SERVICE_TIMEOUT, headers={
                'Authorization': f'APIKey {settings.REPUTATION_SERVICE_TOKEN}'
            }
        )
        if response.status_code == 200:
            try:
                data = response.json()
                if int(data['reputation']) <= cls.reputation_threshold:
                    # Low reputation means we should block that request.
                    log.info('Restricting request from %s %s (%s)',
                             reputation_type, target,
                             'reputation=%s' % data['reputation'])
                    return False
            except (ValueError, KeyError):
                log.exception('Exception calling reputation service for %s %s',
                              reputation_type, target)
        return True


class IPReputationRestriction(
        GetErrorMessageMixin, ReputationRestrictionMixin):
    error_message = IPNetworkUserRestriction.error_message

    @classmethod
    def allow_request(cls, request):
        try:
            remote_addr = ipaddress.ip_address(request.META.get('REMOTE_ADDR'))
        except ValueError:
            # If we don't have a valid ip address, let's deny
            return False

        return cls.allow_reputation('ip', remote_addr)


class EmailReputationRestriction(
        GetErrorMessageMixin, NormalizeEmailMixin, ReputationRestrictionMixin):
    error_message = EmailUserRestriction.error_message

    @classmethod
    def allow_request(cls, request):
        if not request.user.is_authenticated:
            return False

        return cls.allow_reputation('email', cls.normalize_email(
            request.user.email))


class DeveloperAgreementRestriction(GetErrorMessageMixin):
    error_message = _('Before starting, please read and accept our Firefox'
                      ' Add-on Distribution Agreement as well as our Review'
                      ' Policies and Rules. The Firefox Add-on Distribution'
                      ' Agreement also links to our Privacy Notice which'
                      ' explains how we handle your information.')

    @classmethod
    def get_error_message(cls, is_api):
        if is_api:
            from olympia.amo.templatetags.jinja_helpers import absolutify
            url = absolutify(reverse('devhub.api_key'))
            return _('Please read and accept our Firefox Add-on Distribution '
                     'Agreement as well as our Review Policies and Rules '
                     'by visiting {url}'.format(url=url))
        else:
            return cls.error_message

    @classmethod
    def allow_request(cls, request):
        """
        Return whether the specified request should be allowed to submit
        add-ons.
        """
        allowed = (request.user.is_authenticated and
                   request.user.has_read_developer_agreement())
        if not allowed:
            log.info('Restricting request from %s %s (%s)',
                     'developer', request.user.pk, 'agreement')
        return allowed


class UserRestrictionHistory(ModelBase):
    RESTRICTION_CLASSES_CHOICES = (
        (0, DeveloperAgreementRestriction),
        (1, DisposableEmailDomainRestriction),
        (2, EmailUserRestriction),
        (3, IPNetworkUserRestriction),
        (4, EmailReputationRestriction),
        (5, IPReputationRestriction),
    )

    user = models.ForeignKey(
        UserProfile, related_name='restriction_history',
        on_delete=models.CASCADE)
    restriction = models.PositiveSmallIntegerField(
        default=0, choices=tuple(
            (num, klass.__name__) for num, klass in RESTRICTION_CLASSES_CHOICES
        )
    )
    ip_address = models.CharField(default='', max_length=45)
    last_login_ip = models.CharField(default='', max_length=45)


class UserHistory(ModelBase):
    id = PositiveAutoField(primary_key=True)
    email = models.EmailField(max_length=75)
    user = models.ForeignKey(
        UserProfile, related_name='history', on_delete=models.CASCADE)

    class Meta:
        db_table = 'users_history'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('email',), name='users_history_email'),
            models.Index(fields=('user',), name='users_history_user_idx'),
        ]


@UserProfile.on_change
def watch_changes(old_attr=None, new_attr=None, instance=None,
                  sender=None, **kw):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    changes = {
        x for x in new_attr
        if not x.startswith('_') and new_attr[x] != old_attr.get(x)
    }

    # Log email changes.
    if 'email' in changes and new_attr['email'] is not None:
        log.debug('Creating user history for user: %s' % instance.pk)
        UserHistory.objects.create(
            email=old_attr.get('email'), user_id=instance.pk)
    # If username or display_name changes, reindex the user add-ons, if there
    # are any.
    if 'username' in changes or 'display_name' in changes:
        from olympia.addons.tasks import index_addons
        ids = [addon.pk for addon in instance.get_addons_listed()]
        if ids:
            index_addons.delay(ids)

    basket_relevant_changes = (
        'deleted', 'display_name', 'email', 'homepage', 'last_login',
        'location'
    )
    if any(field in changes for field in basket_relevant_changes):
        from olympia.amo.tasks import sync_object_to_basket
        log.info(
            'Triggering a sync of %s %s with basket because of %s change',
            'userprofile', instance.pk, 'attribute')
        sync_object_to_basket.delay('userprofile', instance.pk)


user_logged_in.connect(UserProfile.user_logged_in)
