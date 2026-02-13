import binascii
import ipaddress
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from urllib.parse import urljoin

from django import forms
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.auth.signals import user_logged_in
from django.core import validators
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.db.models import Max, Q
from django.template import loader
from django.template.defaultfilters import slugify
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.translation import gettext, gettext_lazy as _

import requests
import waffle

import olympia.core.logger
from olympia import activity, amo, core
from olympia.access.models import Group, GroupUser
from olympia.amo.decorators import use_primary_db
from olympia.amo.enum import EnumChoices
from olympia.amo.fields import CIDRField, PositiveAutoField
from olympia.amo.models import (
    BaseQuerySet,
    LongNameIndex,
    ManagerBase,
    ModelBase,
    OnChangeMixin,
)
from olympia.amo.utils import (
    backup_storage_enabled,
    download_file_contents_from_backup_storage,
    id_to_path,
)
from olympia.amo.validators import OneOrMoreLetterOrNumberCharacterValidator
from olympia.constants.blocklist import REASON_USER_BANNED
from olympia.files.models import File
from olympia.translations.query import order_by_translation
from olympia.users.notifications import NOTIFICATIONS_BY_ID
from olympia.users.utils import upload_picture


log = olympia.core.logger.getLogger('z.users')


def generate_auth_id():
    """Generate a random integer to be used when generating API auth tokens."""
    # We use MySQL's maximum value for an unsigned int:
    # https://dev.mysql.com/doc/refman/5.7/en/integer-types.html
    return random.SystemRandom().randint(1, 4294967295)


def get_anonymized_username():
    """Gets an anonymized username."""
    return f'anonymous-{force_str(binascii.b2a_hex(os.urandom(16)))}'


class RESTRICTION_TYPES(EnumChoices):
    ADDON_SUBMISSION = 1, 'Add-on Submission'
    ADDON_APPROVAL = 2, 'Add-on Approval'
    RATING = 3, 'Rating'
    RATING_MODERATE = 4, 'Rating Flag for Moderation'


class UserEmailField(forms.ModelChoiceField):
    """
    Field to use for ForeignKeys to UserProfile, to use email instead of pk.
    Requires the form to set the email value in the initial data instead of the
    pk.

    Displays disabled state as readonly thanks to UserEmailBoundField.
    """

    default_error_messages = {'invalid_choice': gettext('No user with that email.')}
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

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            key = self.to_field_name or 'pk'
            if isinstance(value, self.queryset.model):
                value = getattr(value, key)
            # Handle potential multiple users with same email.
            value = self.queryset.filter(**{key: value}).last()
            if value is None:
                raise self.queryset.model.DoesNotExist
        except (ValueError, TypeError, self.queryset.model.DoesNotExist) as exc:
            raise ValidationError(
                self.error_messages['invalid_choice'],
                code='invalid_choice',
                params={'value': value},
            ) from exc
        return value


class UserEmailBoundField(forms.boundfield.BoundField):
    """A BoundField that treats disabled as readonly (enabling users to select
    the text, not suffer from low contrast etc. The form field underneath
    behaves normally and django will still ignore incoming data for it)."""

    def build_widget_attrs(self, *args, **kwargs):
        attrs = super().build_widget_attrs(*args, **kwargs)
        if attrs.get('disabled'):
            attrs.pop('disabled')
            attrs['readonly'] = True
        return attrs


class UserQuerySet(BaseQuerySet):
    def ban_and_disable_related_content(
        self, *, skip_activity_log=False, hard_block_addons=False
    ):
        """Admin method to ban multiple users and disable the content they
        produced.

        Similar to deletion, except that the content produced by the user is
        forcibly soft-disabled instead of being deleted where possible, and the
        user is not anonymized: we keep their data until hard-deletion kicks in
        (see clear_old_user_data), including fxa_id and email so that they are
        never able to log back in.
        """
        from olympia.addons.models import Addon, AddonUser
        from olympia.addons.tasks import index_addons
        from olympia.bandwagon.models import Collection
        from olympia.blocklist.models import BlocklistSubmission
        from olympia.blocklist.tasks import process_blocklistsubmission
        from olympia.ratings.models import Rating
        from olympia.users.tasks import delete_photo

        users = self.all()
        BannedUserContent.objects.bulk_create(
            [BannedUserContent(user=user) for user in users], ignore_conflicts=True
        )
        EmailUserRestriction.objects.bulk_create(
            [
                EmailUserRestriction(
                    email_pattern=EmailUserRestriction.normalize_email(user.email),
                    restriction_type=restriction_type,
                    reason=f'Automatically added because of user {user.pk} ban',
                )
                for user in users
                for restriction_type in [
                    RESTRICTION_TYPES.ADDON_SUBMISSION,
                    RESTRICTION_TYPES.RATING,
                ]
            ],
            ignore_conflicts=True,
        )

        # Collect affected addons
        addon_ids = set(
            Addon.unfiltered.exclude(
                status__in=(amo.STATUS_DELETED, amo.STATUS_DISABLED)
            )
            .filter(addonuser__user__in=users)
            .values_list('id', flat=True)
        )

        # First addons who have other authors we aren't banning - we are
        # keeping the add-ons up, but soft-deleting the relationships.
        addon_joint_ids = set(
            AddonUser.objects.filter(addon_id__in=addon_ids)
            .exclude(user__in=users)
            .values_list('addon_id', flat=True)
        )
        joint_addonusers_qs = AddonUser.objects.filter(
            user__in=users, addon_id__in=addon_joint_ids
        )
        # Keep track of the AddonUser we are (soft-)deleting.
        BannedAddonsUsersModel = BannedUserContent.addons_users.through
        BannedAddonsUsersModel.objects.bulk_create(
            [
                BannedAddonsUsersModel(
                    bannedusercontent_id=val['user'], addonuser_id=val['pk']
                )
                for val in joint_addonusers_qs.values('user', 'pk')
            ]
        )
        # (Soft-)delete them.
        joint_addonusers_qs.delete()

        # Then deal with users who are the sole author - we are disabling them.
        addons_sole = Addon.unfiltered.filter(id__in=addon_ids - addon_joint_ids)
        # set the status to disabled - using the manager update() method
        addons_sole.update(status=amo.STATUS_DISABLED)
        # disable Files in bulk that need to be disabled now the addons are disabled
        Addon.disable_all_files(addons_sole, File.STATUS_DISABLED_REASONS.ADDON_DISABLE)
        # Keep track of the Addons and the relevant user.
        sole_addonusers_qs = AddonUser.objects.filter(
            user__in=users, addon__in=addons_sole
        )
        BannedAddonsModel = BannedUserContent.addons.through
        BannedAddonsModel.objects.bulk_create(
            [
                BannedAddonsModel(
                    bannedusercontent_id=val['user'], addon_id=val['addon']
                )
                for val in sole_addonusers_qs.values('user', 'addon')
            ]
        )

        # Finally run Addon.force_disable to add the logging; update versions.
        addons_sole_ids = []
        for addon in addons_sole:
            addons_sole_ids.append(addon.pk)
            addon.force_disable()
        index_addons.delay(addons_sole_ids)

        # Hard-block all versions of addons we force disabled, if the relevant
        # boolean is True.
        if hard_block_addons:
            submission = BlocklistSubmission(
                action=BlocklistSubmission.ACTIONS.ADDCHANGE,
                input_guids='\r\n'.join([addon.guid for addon in addons_sole]),
                reason=REASON_USER_BANNED,
                updated_by=core.get_user(),
                disable_addon=False,  # Add-ons will already be disabled above.
            )
            submission.changed_version_ids = [
                version.id
                for block in submission.process_input_guids(
                    submission.input_guids, load_full_objects=False
                )['blocks']
                for version in block.addon_versions
                if not version.is_blocked
            ]
            submission.save()
            submission.update_signoff_for_auto_approval()
            if submission.is_submission_ready:
                process_blocklistsubmission.delay(submission.id)

        # Soft-delete the other content associated with the user: Ratings and
        # Collections.
        # Keep track of the Collections
        collections_qs = Collection.objects.filter(author__in=users)
        BannedCollectionsModel = BannedUserContent.collections.through
        BannedCollectionsModel.objects.bulk_create(
            [
                BannedCollectionsModel(
                    bannedusercontent_id=val['author'], collection_id=val['pk']
                )
                for val in collections_qs.values('author', 'pk')
            ]
        )
        # Soft-delete them (keeping their slug - will be restored if unbanned).
        collections_qs.delete()

        # Keep track of the Ratings
        ratings_qs = Rating.objects.filter(user__in=users)
        BannedRatingsModel = BannedUserContent.ratings.through
        BannedRatingsModel.objects.bulk_create(
            [
                BannedRatingsModel(
                    bannedusercontent_id=val['user'], rating_id=val['pk']
                )
                for val in ratings_qs.values('user', 'pk')
            ]
        )
        # Soft-delete them
        ratings_qs.delete()
        # And then ban the users.
        for user in users:
            if not skip_activity_log:
                activity.log_create(amo.LOG.ADMIN_USER_BANNED, user)
            log.info(
                'User (%s: <%s>) is being banned.',
                user,
                user.email,
                extra={'sensitive': True},
            )
            user.banned = user.modified = datetime.now()
            user.deleted = True
            user.auth_id = None  # Reset user sessions
            # To delete their photo, avoid delete_picture() that updates
            # picture_type immediately.
            delete_photo.delay(user.pk, banned=user.banned)
        return self.bulk_update(
            users, fields=('auth_id', 'banned', 'deleted', 'modified')
        )

    def unban_and_reenable_related_content(self, *, skip_activity_log=False):
        """Admin method to unban users and restore their content that was
        disabled when they were banned."""
        for user in self:
            banned_user_content = BannedUserContent.objects.filter(user=user).first()
            if banned_user_content:
                banned_user_content.restore()
            if not skip_activity_log:
                activity.log_create(amo.LOG.ADMIN_USER_UNBAN, user)
            user.deleted = False
            user.banned = None
            user.save()
            EmailUserRestriction.objects.filter(
                email_pattern=EmailUserRestriction.normalize_email(user.email)
            ).delete()


class UserManager(BaseUserManager, ManagerBase):
    _queryset_class = UserQuerySet

    def create_user(self, email, fxa_id=None, **kwargs):
        now = timezone.now()
        user = self.model(email=email, fxa_id=fxa_id, last_login=now, **kwargs)
        log.info(
            'Creating user with email %s and username %s',
            email,
            user.username,
            extra={'sensitive': True},
        )
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

    def ban_and_disable_related_content(self):
        return self.all().ban_and_disable_related_content()

    def unban_and_reenable_related_content(self):
        return self.all().unban_and_reenable_related_content()

    def get_service_account(self, name):
        if not name:
            raise self.model.DoesNotExist('"name" cannot be blank.')

        return self.get(
            username=self._make_username_for_service_account(name),
            fxa_id=None,
            email=None,
        )

    def get_or_create_service_account(self, name, notes=None):
        user, created = self.get_or_create(
            username=self._make_username_for_service_account(name),
            fxa_id=None,
            email=None,
            defaults={
                'notes': notes,
                'read_dev_agreement': datetime.now(),
            },
        )

        if created:
            from olympia.api.models import APIKey

            APIKey.new_jwt_credentials(user=user)

        return user, created

    def _make_username_for_service_account(self, name):
        return slugify(f'service-account-{name}')


class UserProfile(OnChangeMixin, ModelBase, AbstractBaseUser):
    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']
    # These are the fields that will be cleared on UserProfile.delete()
    # last_login_ip is kept, to be deleted later, in line with our data
    # retention policies: https://github.com/mozilla/addons-server/issues/14494
    ANONYMIZED_FIELDS = (
        'auth_id',
        'averagerating',
        'biography',
        'bypass_upload_restrictions',
        'display_name',
        'homepage',
        'has_full_profile',
        'location',
        'occupation',
        'picture_type',
        'read_dev_agreement',
        'username',
    )

    username = models.CharField(
        max_length=255, default=get_anonymized_username, unique=True
    )
    display_name = models.CharField(
        max_length=50,
        default='',
        null=True,
        blank=True,
        validators=[
            validators.MinLengthValidator(2),
            OneOrMoreLetterOrNumberCharacterValidator(),
        ],
    )

    email = models.EmailField(null=True, max_length=75)

    averagerating = models.FloatField(null=True)
    # biography can (and does) contain html and other unsanitized content.
    # It must be cleaned before display.
    biography = models.CharField(blank=True, null=True, max_length=255)
    deleted = models.BooleanField(default=False)
    display_collections = models.BooleanField(default=False)
    homepage = models.URLField(max_length=255, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, null=True)
    occupation = models.CharField(max_length=255, default='', blank=True)
    # This is essentially a "has_picture" flag right now
    picture_type = models.CharField(max_length=75, default=None, null=True, blank=True)
    read_dev_agreement = models.DateTimeField(null=True, blank=True)

    last_login_ip = models.CharField(default='', max_length=45, editable=False)
    email_changed = models.DateTimeField(null=True, editable=False)
    banned = models.DateTimeField(null=True, editable=False)

    # Is the profile page for this account a full profile?
    has_full_profile = models.BooleanField(default=False, db_column='public')

    fxa_id = models.CharField(unique=True, blank=True, null=True, max_length=128)

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

    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=('created',), name='created'),
            models.Index(fields=('email',), name='email'),
            models.Index(fields=('fxa_id',), name='users_fxa_id_index'),
            LongNameIndex(
                fields=('last_login_ip',), name='users_last_login_ip_2cfbbfbd'
            ),
        ]

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.username:
            self.username = force_str(self.username)

    def __str__(self):
        return f'{self.id}: {self.display_name or self.username}'

    @property
    def is_superuser(self):
        return any(group.rules == '*:*' for group in self.groups_list)

    @property
    def is_staff(self):
        """Property indicating whether the user is considered to be a Mozilla
        Employee.

        Django admin uses this to allow logging in, though it doesn't give
        access to the individual admin pages: each module has their own
        permission checks (see has_module_perms() and has_perm() below). In
        addition we also force users to use the VPN to access the admin.

        It's also used by waffle Flag `staff` property, which allows a feature
        behind a flag to be enabled just for users for which this property
        returns True. This shouldn't be used as a replacement to a permission
        check, but only for progressive rollouts of features that are intended
        to eventually be enabled globally.
        """
        return self.email and self.email.endswith('@mozilla.com')

    def has_perm(self, perm, obj=None):
        """Determine what the user can do in the django admin tools.

        perm is in the form "<app>.<action>_<model>".
        """
        from olympia.access import acl

        return acl.action_allowed_for(
            self, amo.permissions.DJANGO_PERMISSIONS_MAPPING[perm]
        )

    def has_module_perms(self, app_label):
        """Determine whether the user can see a particular app in the django
        admin tools."""
        # If the user is a superuser or has permission for any action available
        # for any of the models of the app, they can see the app in the django
        # admin. The is_superuser check is needed to allow superuser to access
        # modules that are not in the mapping at all (i.e. things only they
        # can access).
        return self.is_superuser or any(
            self.has_perm(key)
            for key in amo.permissions.DJANGO_PERMISSIONS_MAPPING
            if key.startswith('%s.' % app_label)
        )

    def has_read_developer_agreement(self):
        from olympia.zadmin.models import get_config

        if self.read_dev_agreement is None:
            return False
        last_agreement_change_config = None
        try:
            last_agreement_change_config = get_config(
                amo.config_keys.LAST_DEV_AGREEMENT_CHANGE_DATE
            )
            change_config_date = datetime.strptime(
                last_agreement_change_config, '%Y-%m-%d %H:%M'
            )

            # If the config date is in the future, instead check against the
            # fallback date
            if change_config_date > datetime.now():
                return self.read_dev_agreement > settings.DEV_AGREEMENT_CHANGE_FALLBACK

            return self.read_dev_agreement > change_config_date
        except (ValueError, TypeError):
            log.exception(
                'last_developer_agreement_change misconfigured, "%s" is not a datetime',
                last_agreement_change_config,
            )
            return self.read_dev_agreement > settings.DEV_AGREEMENT_CHANGE_FALLBACK

    def get_session_auth_hash(self):
        """Return a hash used to invalidate sessions of users when necessary.

        Can return None if auth_id is not set on this user, which effectively
        invalidates the session automatically as auth_id has a non-None default
        value."""
        if self.auth_id is None or self.deleted:
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

    def get_url_path(self, src=None):
        return self.create_user_url(self.id, src=src)

    @cached_property
    def groups_list(self):
        """List of all groups the user is a member of, as a cached property."""
        return list(self.groups.all())

    def get_addons_listed(self):
        """Return queryset of public add-ons thi user is listed as author of."""
        return self.addons.public().filter(addonuser__user=self, addonuser__listed=True)

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
        return os.path.join(
            settings.MEDIA_ROOT, 'userpics', id_to_path(self.pk, breadth=2)
        )

    @property
    def picture_path(self):
        return os.path.join(self.picture_dir, str(self.pk) + '.png')

    @property
    def picture_path_original(self):
        return os.path.join(self.picture_dir, str(self.pk) + '_original.png')

    @property
    def picture_url(self):
        if not self.picture_type:
            return static('img/zamboni/anon_user.png')
        else:
            modified = int(time.mktime(self.modified.timetuple()))
            path = '/'.join(
                [
                    id_to_path(self.pk, breadth=2),
                    f'{self.pk}.png?modified={modified}',
                ]
            )
            return f'{settings.MEDIA_URL}userpics/{path}'

    @cached_property
    def cached_developer_status(self):
        addon_types = list(
            self.addonuser_set.exclude(addon__status=amo.STATUS_DELETED).values_list(
                'addon__type', flat=True
            )
        )

        all_themes = [t for t in addon_types if t in amo.GROUP_TYPE_THEME]
        return {
            'is_developer': bool(addon_types),
            'is_extension_developer': len(all_themes) != len(addon_types),
            'is_theme_developer': bool(all_themes),
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
    def update_has_full_profile(self):
        pre = self.has_full_profile
        has_full_profile = self.addonuser_set.filter(
            role__in=[amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV],
            listed=True,
            addon__status=amo.STATUS_APPROVED,
        ).exists()
        if has_full_profile != pre:
            log.info(
                'Updating %s.has_full_profile from %s to %s',
                self.pk,
                pre,
                has_full_profile,
            )
            self.update(has_full_profile=has_full_profile)
        else:
            log.info('Not changing %s.has_full_profile from %s', self.pk, pre)

    @property
    def name(self) -> str:
        if self.display_name:
            return force_str(self.display_name)
        else:
            return gettext('Firefox user {id}').format(id=self.id)

    welcome_name = name

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name

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

    def _delete_related_content(self, *, addon_msg=''):
        """Delete content produced by this user if they are the only author."""
        self.collections.all().delete()
        for addon in self.addons.all().iterator():
            if not addon.authors.exclude(pk=self.pk).exists():
                addon.delete(msg=addon_msg)
            else:
                addon.addonuser_set.get(user=self).delete()
        self._ratings_all.all().delete()

    def delete_picture(self):
        """Delete picture of this user."""
        # Recursive import
        from olympia.users.tasks import delete_photo

        delete_photo.delay(self.pk)

        if self.picture_type:
            self.update(picture_type=None)

    def anonymize_user(self):
        fields = {
            field_name: self._meta.get_field(field_name)
            for field_name in self.ANONYMIZED_FIELDS
        }
        log.info('Anonymizing user %s', self.pk)
        for field_name, field in fields.items():
            setattr(self, field_name, field.get_default())
        self.delete_picture()

    def _prepare_delete_email(self):
        site_url = settings.EXTERNAL_SITE_URL
        template = loader.get_template('users/emails/user_deleted.ltxt')
        email_msg = template.render(
            context={
                'site_url': site_url,
                'name': self.name,
            }
        )
        return {
            'subject': f'Your account on {site_url} has been deleted',
            'message': email_msg,
            'recipient_list': [str(self.email)],
        }

    def should_send_delete_email(self):
        return (
            self.display_name
            or self.addons.exists()
            or self.ratings.exists()
            or self.collections.exists()
        )

    def delete(self, addon_msg=''):
        from olympia.amo.utils import send_mail

        send_delete_email = self.should_send_delete_email()
        self._delete_related_content(addon_msg=addon_msg)
        log.info('User (%s: <%s>) is being anonymized.', self, self.email)
        email = self._prepare_delete_email() if send_delete_email else None
        self.anonymize_user()
        self.deleted = True
        self.save()
        if send_delete_email:
            send_mail(**email)

    def set_unusable_password(self):
        raise NotImplementedError('cannot set unusable password')

    def set_password(self, password):
        raise NotImplementedError('cannot set password')

    def check_password(self, password):
        raise NotImplementedError('cannot check password')

    @staticmethod
    def user_logged_in(sender, request, user, **kwargs):
        """Log when a user logs in and records its IP address."""
        # The following log statement is used by foxsec-pipeline.
        log.info('User (%s) logged in successfully', user, extra={'email': user.email})
        user.update(last_login_ip=core.get_remote_addr() or '')
        action = (
            amo.LOG.LOG_IN_API_TOKEN
            if kwargs.get('using_api_token')
            else amo.LOG.LOG_IN
        )
        activity.log_create(action, user=user)

    @property
    def suppressed_email(self):
        return SuppressedEmail.objects.filter(email=self.email).first()

    @property
    def email_verification(self):
        return SuppressedEmailVerification.objects.filter(
            suppressed_email=self.suppressed_email
        ).first()

    def is_survey_eligible(self, survey_id):
        if survey_id not in amo.ACTIVE_SURVEYS:
            raise ValueError('Given survey_id is not a valid survey.')
        return (
            self.addons.filter(
                last_updated__gte=(timezone.now() - timedelta(days=30))
            ).exists()
            and not self.surveyresponse.filter(
                user=self,
                survey_id=survey_id,
                date_responded__gte=(timezone.now() - timedelta(days=180)),
            ).exists()
        )


class UserNotification(ModelBase):
    user = models.ForeignKey(
        UserProfile, related_name='notifications', on_delete=models.CASCADE
    )
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
        return '{user}, {notification}, enabled={enabled}'.format(
            user=self.user.name,
            notification=self.notification.short,
            enabled=self.enabled,
        )


class DeniedName(ModelBase):
    """Denied User usernames and display_names + Collections' names."""

    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'users_denied_name'

    def __str__(self):
        return self.name


class RestrictionAbstractBase:
    """Base class for restrictions."""

    @classmethod
    def allow_submission(cls, request):
        """
        Return whether the specified request should be allowed to submit
        add-ons.
        """
        return cls.allow_request(
            request, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    @classmethod
    def allow_auto_approval(cls, upload):
        """
        Return whether the specified version should be allowed to be proceed
        through auto-approval process.
        """
        # Should be implemented by child classes.
        raise NotImplementedError

    @classmethod
    def allow_rating(cls, request):
        """
        Return whether the specified request should be allowed to submit ratings.
        """
        return cls.allow_request(request, restriction_type=RESTRICTION_TYPES.RATING)

    @classmethod
    def allow_rating_without_moderation(cls, request):
        """
        Return whether ratings from the specified request should not be flagged for
        moderation.
        """
        return cls.allow_request(
            request, restriction_type=RESTRICTION_TYPES.RATING_MODERATE
        )

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        """
        Return whether the specified request should be allowed for the given
        restriction type.
        """
        # Should be implemented by child classes.
        raise NotImplementedError

    @classmethod
    def get_error_message(cls, is_api):
        return cls.error_message


class RestrictionAbstractBaseModel(ModelBase, RestrictionAbstractBase):
    """Base class for restrictions that are backed by the database."""

    restriction_type = models.PositiveSmallIntegerField(
        default=RESTRICTION_TYPES.ADDON_SUBMISSION, choices=RESTRICTION_TYPES.choices
    )
    reason = models.CharField(
        blank=True,
        null=True,
        max_length=255,
        help_text='Private description of why this restriction was added.',
    )

    class Meta:
        abstract = True


class IPNetworkUserRestriction(RestrictionAbstractBaseModel):
    id = PositiveAutoField(primary_key=True)
    network = CIDRField(
        blank=True,
        null=True,
        help_text='Enter a valid IPv4 or IPv6 CIDR network range, eg. 127.0.0.1/28',
    )

    error_message = _(
        'Multiple submissions violating our policies have been sent from your '
        'location. The IP address has been blocked.'
    )

    class Meta:
        db_table = 'users_user_network_restriction'
        constraints = [
            models.UniqueConstraint(
                fields=('network', 'restriction_type'),
                name='network_restriction_type_uniq',
            )
        ]

    def __str__(self):
        return str(self.network)

    @classmethod
    def network_from_ip(cls, ip):
        """
        Return the smallest meaningful network to restrict from an IP
        """
        ip_object = ipaddress.ip_address(ip)
        # For IPv4, restrict the /32, i.e. the exact IP.
        # For IPv6, restrict the /64, otherwise the restriction would be
        # trivial to bypass. We pass strict=False to ip_network() to make the
        # ipaddress module ignore the hosts bits from the ip after the prefix
        # length is applied.
        prefix_len = 32 if ip_object.version == 4 else 64
        network = ipaddress.ip_network((ip, prefix_len), strict=False)
        return network

    @classmethod
    def allow_auto_approval(cls, upload):
        if not upload.user or not upload.ip_address:
            return False

        try:
            remote_addr = ipaddress.ip_address(upload.ip_address)
            user_last_login_ip = ipaddress.ip_address(upload.user.last_login_ip)
        except ValueError:
            # If we don't have a valid ip address, let's deny
            return False

        return cls.allow_ips(
            remote_addr,
            user_last_login_ip,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        try:
            remote_addr = ipaddress.ip_address(request.META.get('REMOTE_ADDR'))
            user_last_login_ip = (
                ipaddress.ip_address(request.user.last_login_ip)
                if request.user
                else None
            )
        except ValueError:
            # If we don't have a valid ip address, let's deny
            return False

        return cls.allow_ips(
            remote_addr, user_last_login_ip, restriction_type=restriction_type
        )

    @classmethod
    def allow_ips(self, remote_addr, user_last_login_ip, *, restriction_type):
        restrictions = IPNetworkUserRestriction.objects.all().filter(
            restriction_type=restriction_type
        )
        for restriction in restrictions:
            if (
                remote_addr in restriction.network
                or user_last_login_ip in restriction.network
            ):
                # The following log statement is used by foxsec-pipeline.
                log.info(
                    'Restricting request from %s %s, %s %s (%s)',
                    'ip',
                    remote_addr,
                    'last_login_ip',
                    user_last_login_ip,
                    'network=%s' % restriction.network,
                    extra={'sensitive': True},
                )
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
        normalized_email = f'{local_part}@{domain}'
        if normalized_email != email:
            log.info(
                'Normalized email from %s to %s',
                email,
                normalized_email,
                extra={'sensitive': True},
            )
        return normalized_email


class EmailUserRestrictionManager(ManagerBase):
    def get_or_create(self, defaults=None, **kwargs):
        if (email_pattern := kwargs.get('email_pattern')) and '@' in email_pattern:
            kwargs['email_pattern'] = EmailUserRestriction.normalize_email(
                email_pattern
            )
        return super().get_or_create(defaults=defaults, **kwargs)


class EmailUserRestriction(RestrictionAbstractBaseModel, NormalizeEmailMixin):
    id = PositiveAutoField(primary_key=True)
    email_pattern = models.CharField(
        'Email Pattern',
        max_length=100,
        help_text=(
            'Enter full email that should be blocked or use unix-style wildcards, '
            'e.g. "*@example.com". If you need to block a domain incl subdomains, '
            'add a second entry, e.g. "*@*.example.com".'
        ),
    )

    error_message = _(
        'The email address used for your account is not allowed for submissions.'
    )

    objects = EmailUserRestrictionManager()

    class Meta:
        db_table = 'users_user_email_restriction'
        constraints = [
            models.UniqueConstraint(
                fields=('email_pattern', 'restriction_type'),
                name='email_pattern_restriction_type_uniq',
            )
        ]

    def __str__(self):
        return str(self.email_pattern)

    def save(self, **kw):
        if '@' in self.email_pattern:
            self.email_pattern = self.normalize_email(self.email_pattern)
        super().save(**kw)

    @classmethod
    def allow_auto_approval(cls, upload):
        if not upload.user:
            return False
        return cls.allow_email(
            upload.user.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        if not request.user.is_authenticated:
            return False

        return cls.allow_email(request.user.email, restriction_type=restriction_type)

    @classmethod
    def allow_email(cls, email, *, restriction_type):
        """
        Return whether the specified email should be allowed to submit add-ons.
        """
        email = cls.normalize_email(email)
        base_qs = EmailUserRestriction.objects.all().filter(
            restriction_type=restriction_type
        )

        # We should have relatively few restrictions with actual patterns, so
        # we can grab them all from the database to see if they match without
        # worrying about performance impact, but we can have a lot more with
        # just the raw email, so test against those with a specific query to
        # avoid loading all of them.
        matching_restriction = base_qs.filter(email_pattern=email).first()
        if not matching_restriction:
            complex_restrictions = base_qs.filter(
                Q(email_pattern__contains='?')
                | Q(email_pattern__contains='*')
                | Q(email_pattern__contains='[')
            )
            for restriction in complex_restrictions:
                if fnmatchcase(email, restriction.email_pattern):
                    matching_restriction = restriction
                    break

        if matching_restriction:
            # The following log statement is used by foxsec-pipeline.
            log.info(
                'Restricting request from %s %s (%s)',
                'email',
                email,
                'email_pattern=%s' % matching_restriction.email_pattern,
                extra={'sensitive': True},
            )
            return False

        return True


class DisposableEmailDomainRestriction(RestrictionAbstractBaseModel):
    domain = models.CharField(
        max_length=255,
        help_text=(
            'Enter full disposable email domain that should be '
            'blocked. Wildcards are not supported: if you need those, '
            'or need to match against the entire email and not just '
            'the domain part, use "Email user restrictions" instead.'
        ),
    )

    error_message = EmailUserRestriction.error_message

    class Meta:
        db_table = 'users_disposable_email_domain_restriction'
        constraints = [
            models.UniqueConstraint(
                fields=('domain', 'restriction_type'),
                name='domain_restriction_type_uniq',
            )
        ]

    def __str__(self):
        return str(self.domain)

    @classmethod
    def allow_auto_approval(cls, upload):
        if not upload.user:
            return False
        return cls.allow_email(
            upload.user.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        if not request.user.is_authenticated:
            return False

        return cls.allow_email(request.user.email, restriction_type=restriction_type)

    @classmethod
    def allow_email(cls, email, *, restriction_type):
        email_domain = email.rsplit('@', maxsplit=1)[-1]

        # Unlike EmailUserRestriction we can use .exists() directly. This
        # allows us to have thousands of entries without perf issues.
        return not cls.objects.filter(
            domain=email_domain, restriction_type=restriction_type
        ).exists()


class FingerprintRestriction(RestrictionAbstractBaseModel):
    ja4 = models.CharField(max_length=36, db_index=True)

    error_message = _(
        'The software or device you are using is not allowed for submissions.'
    )

    class Meta:
        db_table = 'users_fingerprint_restriction'
        constraints = [
            models.UniqueConstraint(
                fields=('ja4', 'restriction_type'),
                name='ja4_restriction_type_uniq',
            )
        ]

    def __str__(self):
        return str(self.ja4)

    @classmethod
    def allow_ja4(cls, ja4, *, restriction_type):
        return not cls.objects.filter(
            ja4=ja4, restriction_type=restriction_type
        ).exists()

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        if not (ja4 := request.headers.get('Client-JA4')):
            return True
        return cls.allow_ja4(ja4, restriction_type=restriction_type)

    @classmethod
    def allow_auto_approval(cls, upload):
        if not upload.request_metadata or not (
            ja4 := upload.request_metadata.get('Client-JA4')
        ):
            return True
        return cls.allow_ja4(ja4, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL)


class ReputationRestrictionMixin:
    reputation_threshold = 50

    @classmethod
    def allow_auto_approval(cls, upload):
        # Reputation-based restriction is only applied at submission, it's more
        # an anti-spam measure than something applied after the fact at the
        # moment.
        return True

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
        if (
            not settings.REPUTATION_SERVICE_URL
            or not settings.REPUTATION_SERVICE_TOKEN
            or settings.REPUTATION_SERVICE_TIMEOUT is None
        ):
            return True  # Not configured.
        url = urljoin(
            settings.REPUTATION_SERVICE_URL, f'/type/{reputation_type}/{target}'
        )
        response = requests.get(
            url,
            timeout=settings.REPUTATION_SERVICE_TIMEOUT,
            headers={'Authorization': f'APIKey {settings.REPUTATION_SERVICE_TOKEN}'},
        )
        if response.status_code == 200:
            try:
                data = response.json()
                if int(data['reputation']) <= cls.reputation_threshold:
                    # Low reputation means we should block that request.
                    # The following log statement is used by foxsec-pipeline.
                    log.info(
                        'Restricting request from %s %s (%s)',
                        reputation_type,
                        target,
                        'reputation=%s' % data['reputation'],
                        extra={'sensitive': True},
                    )
                    return False
            except (ValueError, KeyError):
                log.exception(
                    'Exception calling reputation service for %s %s',
                    reputation_type,
                    target,
                    extra={'sensitive': True},
                )
        return True


class IPReputationRestriction(ReputationRestrictionMixin, RestrictionAbstractBase):
    error_message = IPNetworkUserRestriction.error_message

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        try:
            remote_addr = ipaddress.ip_address(request.META.get('REMOTE_ADDR'))
        except ValueError:
            # If we don't have a valid ip address, let's deny
            return False

        return cls.allow_reputation('ip', remote_addr)


class EmailReputationRestriction(
    ReputationRestrictionMixin, RestrictionAbstractBase, NormalizeEmailMixin
):
    error_message = EmailUserRestriction.error_message

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        if not request.user.is_authenticated:
            return False

        return cls.allow_reputation('email', cls.normalize_email(request.user.email))


class DeveloperAgreementRestriction(RestrictionAbstractBase):
    error_message = _(
        'Before starting, please read and accept our Firefox'
        ' Add-on Distribution Agreement as well as our Review'
        ' Policies and Rules. The Firefox Add-on Distribution'
        ' Agreement also links to our Privacy Notice which'
        ' explains how we handle your information.'
    )

    @classmethod
    def get_error_message(cls, is_api):
        if is_api:
            from olympia.amo.templatetags.jinja_helpers import absolutify

            url = absolutify(reverse('devhub.api_key'))
            return _(
                'Please read and accept our Firefox Add-on Distribution '
                'Agreement as well as our Review Policies and Rules '
                'by visiting {url}'.format(url=url)
            )
        else:
            return cls.error_message

    @classmethod
    def allow_auto_approval(cls, upload):
        # DeveloperRestriction is only relevant at add-on submission time.
        return True

    @classmethod
    def allow_request(cls, request, *, restriction_type):
        """
        Return whether the specified request should be allowed for the given
        restriction type.
        """
        allowed = restriction_type != RESTRICTION_TYPES.ADDON_SUBMISSION or (
            request.user.is_authenticated
            and request.user.has_read_developer_agreement()
        )
        if not allowed:
            # The following log statement is used by foxsec-pipeline.
            log.info(
                'Restricting request from %s %s (%s)',
                'developer',
                request.user.pk,
                'agreement',
            )
        return allowed


class UserRestrictionHistory(ModelBase):
    RESTRICTION_CLASSES_CHOICES = (
        (0, DeveloperAgreementRestriction),
        (1, DisposableEmailDomainRestriction),
        (2, EmailUserRestriction),
        (3, IPNetworkUserRestriction),
        (4, EmailReputationRestriction),
        (5, IPReputationRestriction),
        (6, FingerprintRestriction),
    )

    user = models.ForeignKey(
        UserProfile, related_name='restriction_history', on_delete=models.CASCADE
    )
    restriction = models.PositiveSmallIntegerField(
        default=0,
        choices=tuple(
            (num, klass.__name__) for num, klass in RESTRICTION_CLASSES_CHOICES
        ),
    )
    ip_address = models.CharField(default='', max_length=45)
    last_login_ip = models.CharField(default='', max_length=45)

    class Meta:
        verbose_name_plural = 'User Restriction History'
        indexes = [
            LongNameIndex(
                fields=('ip_address',),
                name='users_userrestrictionhistory_ip_address_4376df32',
            ),
            LongNameIndex(
                fields=('last_login_ip',),
                name='users_userrestrictionhistory_last_login_ip_d58d95ff',
            ),
        ]


class UserHistory(ModelBase):
    id = PositiveAutoField(primary_key=True)
    email = models.EmailField(max_length=75)
    user = models.ForeignKey(
        UserProfile, related_name='history', on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'users_history'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('email',), name='users_history_email'),
            models.Index(fields=('user',), name='users_history_user_idx'),
        ]

    def __str__(self):
        return f'{self.user_id}: {self.email}'


@UserProfile.on_change
def watch_changes(old_attr=None, new_attr=None, instance=None, sender=None, **kw):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    changes = {
        x for x in new_attr if not x.startswith('_') and new_attr[x] != old_attr.get(x)
    }

    # Log email changes.
    if (
        'email' in changes
        and new_attr['email'] is not None
        and old_attr.get('email') is not None
    ):
        log.info('Creating user history for user: %s', instance.pk)
        UserHistory.objects.create(email=old_attr.get('email'), user_id=instance.pk)
    # If username or display_name changes, reindex the user add-ons, if there
    # are any.
    if 'username' in changes or 'display_name' in changes:
        from olympia.addons.tasks import index_addons
        from olympia.scanners.tasks import run_narc_on_version

        ids = [addon.pk for addon in instance.get_addons_listed()]
        if ids:
            index_addons.delay(ids)

        if waffle.switch_is_active('enable-narc'):
            # Re-run narc scanner on the last non rejected version of their
            # non-disabled by Mozilla add-ons - this is a slightly larger set
            # than the one used above for reindexing, as we want to include
            # add-ons and versions disabled by their developers, to scan them
            # before they would be re-enabled.
            version_pks = (
                instance.addons.not_disabled_by_mozilla()
                .annotate(
                    last_version_id=Max(
                        'versions',
                        filter=Q(
                            versions__channel=amo.CHANNEL_LISTED,
                            versions__deleted=False,
                        )
                        & ~Q(
                            versions__file__status=amo.STATUS_DISABLED,
                            versions__file__status_disabled_reason=(
                                File.STATUS_DISABLED_REASONS.NONE
                            ),
                        ),
                    )
                )
                .exclude(last_version_id=None)
                .values_list('last_version_id', flat=True)
                .order_by('last_version_id')
            )
            for version_pk in version_pks:
                run_narc_on_version.delay(version_pk)


user_logged_in.connect(UserProfile.user_logged_in)


class BannedUserContent(ModelBase):
    """Link between a user and the content that was disabled when they were
    banned.

    That link should be removed if the user is unbanned, and the content
    re-enabled.
    """

    user = models.OneToOneField(
        UserProfile,
        related_name='content_disabled_on_ban',
        on_delete=models.CASCADE,
        primary_key=True,
    )
    collections = models.ManyToManyField('bandwagon.Collection')
    addons = models.ManyToManyField('addons.Addon')
    addons_users = models.ManyToManyField('addons.AddonUser')
    ratings = models.ManyToManyField('ratings.Rating')
    picture_backup_name = models.CharField(
        max_length=75, default=None, null=True, blank=True
    )
    picture_type = models.CharField(max_length=75, default=None, null=True, blank=True)

    def restore_picture(self):
        if self.picture_backup_name and backup_storage_enabled():
            file_contents = download_file_contents_from_backup_storage(
                self.picture_backup_name
            )
            upload = SimpleUploadedFile(
                self.picture_backup_name,
                file_contents,
                content_type=self.picture_type,
            )
            upload_picture(self.user, upload)

    def restore(self):
        for relation in ('addons_users', 'collections', 'ratings'):
            getattr(self, relation)(manager='unfiltered_for_relations').all().undelete()
        # Add-ons are special as they are force-disabled on ban, not
        # soft-deleted.
        for addon in self.addons.all():
            addon.force_enable()
        try:
            self.restore_picture()
        except Exception as e:
            # If something wrong happens here, we won't restore the picture
            # but we want to be able to continue.
            log.exception(e)
        activity.log_create(amo.LOG.ADMIN_USER_CONTENT_RESTORED, self.user)
        self.delete()  # Should delete the ManyToMany relationships


class SuppressedEmail(ModelBase):
    email = models.EmailField(unique=True, null=False, max_length=75)


class SuppressedEmailVerification(ModelBase):
    class STATUS_CHOICES(EnumChoices):
        PENDING = 0, 'Pending'
        DELIVERED = 1, 'Delivered'
        FAILED = 2, 'Failed'

    confirmation_code = models.CharField(
        max_length=255, null=False, blank=False, default=uuid.uuid4
    )
    suppressed_email = models.OneToOneField(
        SuppressedEmail,
        related_name='suppressed_email',
        on_delete=models.CASCADE,
    )
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES.choices, default=STATUS_CHOICES.PENDING
    )

    @property
    def expiration(self):
        return self.created + timedelta(days=30)

    @property
    def is_expired(self):
        return self.expiration < datetime.now()

    @property
    def is_timedout(self):
        return self.created + timedelta(minutes=10) < datetime.now()

    def mark_as_delivered(self):
        self.update(status=SuppressedEmailVerification.STATUS_CHOICES.DELIVERED)
        self.save()
