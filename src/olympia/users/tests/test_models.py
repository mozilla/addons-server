import os.path
from datetime import date, datetime, timedelta
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from unittest import mock

from django import forms
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.db import models
from django.db.utils import IntegrityError
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.utils import timezone

import pytest
import responses
import time_machine

from olympia import amo, core
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.amo.utils import SafeStorage
from olympia.api.models import APIKey
from olympia.bandwagon.models import Collection
from olympia.devhub.models import SurveyResponse
from olympia.files.models import File, FileUpload
from olympia.ratings.models import Rating
from olympia.users.models import (
    RESTRICTION_TYPES,
    BannedUserContent,
    DisposableEmailDomainRestriction,
    EmailReputationRestriction,
    EmailUserRestriction,
    FingerprintRestriction,
    IPNetworkUserRestriction,
    IPReputationRestriction,
    SuppressedEmail,
    SuppressedEmailVerification,
    UserEmailField,
    UserProfile,
    generate_auth_id,
    get_anonymized_username,
)
from olympia.zadmin.models import set_config


class TestUserProfile(TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'users/test_backends')

    def setUp(self):
        self.storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')

    def test_logged_in(self):
        user = user_factory()
        with core.override_remote_addr_or_metadata(ip_address='4.8.15.16'):
            self.client.force_login(user)
        user.reload()
        assert user.last_login_ip == '4.8.15.16'
        assert ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).count() == 1
        log = ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).latest('pk')
        assert log.user == user
        assert log.iplog.ip_address_binary == IPv4Address('4.8.15.16')

        with core.override_remote_addr_or_metadata(ip_address='23.42.42.42'):
            self.client.force_login(user)
        assert user.last_login_ip == '23.42.42.42'
        assert ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).count() == 2
        log = ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).latest('pk')
        assert log.user == user
        assert log.iplog.ip_address_binary == IPv4Address('23.42.42.42')

    def test_is_addon_developer(self):
        user = user_factory()
        assert not user.addonuser_set.exists()
        assert not user.is_developer
        assert not user.is_addon_developer
        assert not user.is_artist

        addon = addon_factory(users=[user])
        del user.cached_developer_status  # it's a cached property.
        assert user.is_developer
        assert user.is_addon_developer
        assert not user.is_artist

        addon.delete()
        del user.cached_developer_status
        assert not user.is_developer
        assert not user.is_addon_developer
        assert not user.is_artist

    def test_is_artist_of_static_theme(self):
        user = user_factory()
        assert not user.addonuser_set.exists()
        assert not user.is_developer
        assert not user.is_addon_developer
        assert not user.is_artist

        addon = addon_factory(users=[user], type=amo.ADDON_STATICTHEME)
        del user.cached_developer_status  # it's a cached property.
        assert user.is_developer
        assert not user.is_addon_developer
        assert user.is_artist

        addon.delete()
        del user.cached_developer_status
        assert not user.is_developer
        assert not user.is_addon_developer
        assert not user.is_artist

    def test_delete(self):
        user = UserProfile.objects.get(pk=4043307)

        # Create a photo so that we can test deletion.
        with self.storage.open(user.picture_path, 'wb') as fobj:
            fobj.write(b'test data\n')

        with self.storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write(b'original test data\n')

        assert self.storage.exists(user.picture_path_original)
        assert self.storage.exists(user.picture_path)

        assert not user.deleted
        assert user.email == 'jbalogh@mozilla.com'
        assert user.auth_id
        assert user.fxa_id == '0824087ad88043e2a52bd41f51bbbe79'
        assert user.username == 'jbalogh'
        assert user.display_name
        assert user.homepage
        assert user.picture_type
        assert user.last_login_ip
        assert not user.has_anonymous_username
        name = user.display_name
        user.update(
            averagerating=4.4,
            biography='some life',
            bypass_upload_restrictions=True,
            location='some where',
            occupation='some job',
            read_dev_agreement=datetime.now(),
        )

        old_auth_id = user.auth_id
        user.delete()
        user = UserProfile.objects.get(pk=4043307)
        assert user.email == 'jbalogh@mozilla.com'
        assert user.auth_id
        assert user.auth_id != old_auth_id
        assert user.fxa_id == '0824087ad88043e2a52bd41f51bbbe79'
        assert user.display_name == ''
        assert user.homepage == ''
        assert user.picture_type is None
        # last_login_ip is kept during deletion and later via
        # clear_old_user_data command
        assert user.last_login_ip
        assert user.has_anonymous_username
        assert user.averagerating is None
        assert user.biography is None
        assert user.bypass_upload_restrictions is False
        assert user.location == ''
        assert user.occupation == ''
        assert user.read_dev_agreement is None
        assert not self.storage.exists(user.picture_path)
        assert not self.storage.exists(user.picture_path_original)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == [user.email]
        assert f'message because your user account {name}' in email.body
        self.assertCloseToNow(user.modified)

    def test_should_send_delete_email(self):
        no_name = user_factory(email='email@moco', occupation='person')
        assert not no_name.should_send_delete_email()

        no_name.update(display_name='Steve Holt!')
        assert no_name.should_send_delete_email()

        addon_owner = user_factory()
        addon = addon_factory(users=(addon_owner,))
        assert addon_owner.should_send_delete_email()

        collection_creator = collection_factory(author=user_factory()).author
        assert collection_creator.should_send_delete_email()

        rating_writer = user_factory()
        Rating.objects.create(
            user=rating_writer, addon=addon, version=addon.current_version
        )
        assert rating_writer.should_send_delete_email()

    @mock.patch('olympia.users.tasks.copy_file_to_backup_storage')
    @mock.patch('olympia.users.tasks.backup_storage_enabled', lambda: True)
    def test_ban_and_disable_related_content_bulk(
        self, copy_file_to_backup_storage_mock
    ):
        copy_file_to_backup_storage_mock.side_effect = (
            lambda local_path, content_type: os.path.basename(local_path)
        )
        user_sole = user_factory(
            auth_id=123456789,
            email='sole@foo.baa',
            fxa_id='13579',
            last_login_ip='127.0.0.1',
            averagerating=4.4,
            biography='ban me',
            bypass_upload_restrictions=True,
            location='some where',
            occupation='some job',
            read_dev_agreement=datetime.now(),
        )
        addon_sole = addon_factory(users=[user_sole])
        addon_sole_file = addon_sole.current_version.file
        self.setup_user_to_be_have_content_disabled(user_sole)
        user_multi = user_factory(
            auth_id=987654321,
            email='multi.addons@foo.baa',
            fxa_id='24680',
            last_login_ip='127.0.0.2',
            averagerating=2.2,
            biography='ban me too',
            bypass_upload_restrictions=True,
            location='some where too',
            occupation='some job too',
            read_dev_agreement=datetime.now(),
        )
        user_innocent = user_factory()
        addon_multi = addon_factory(
            users=UserProfile.objects.filter(id__in=[user_multi.id, user_innocent.id])
        )
        addon_multi_file = addon_multi.current_version.file
        self.setup_user_to_be_have_content_disabled(user_multi)

        Rating.objects.create(user=user_innocent, addon=addon_multi, rating=5)

        # Add existing EmailUserRestriction for user sole email, it should not
        # matter, we shouldn't add a duplicate.
        EmailUserRestriction.objects.create(
            email_pattern=user_sole.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
            reason='Already exists',
        )

        # Now that everything is set up, disable/delete related content.
        UserProfile.objects.filter(
            pk__in=(user_sole.pk, user_multi.pk)
        ).ban_and_disable_related_content()

        assert copy_file_to_backup_storage_mock.call_count == 2

        user_sole.reload()
        user_multi.reload()

        addon_sole.reload()
        addon_multi.reload()
        # if sole dev should have been disabled, but the author retained
        assert addon_sole.status == amo.STATUS_DISABLED
        assert list(addon_sole.authors.all()) == [user_sole]
        # shouldn't have been disabled as it has another author
        assert addon_multi.status != amo.STATUS_DISABLED
        assert list(addon_multi.authors.all()) == [user_innocent]

        # the File objects have been disabled
        addon_sole_file.reload()
        assert addon_sole_file.status == amo.STATUS_DISABLED
        assert addon_sole_file.original_status == amo.STATUS_APPROVED
        assert (
            addon_sole_file.status_disabled_reason
            == File.STATUS_DISABLED_REASONS.ADDON_DISABLE
        )
        # But not for the Add-on that wasn't disabled
        assert addon_multi_file.reload().status == amo.STATUS_APPROVED

        assert not user_sole._ratings_all.exists()  # Even replies.
        assert not user_sole.collections.exists()
        assert user_sole._ratings_all(manager='unfiltered_for_relations').exists()
        assert user_sole.collections(manager='unfiltered_for_relations').exists()
        assert not user_multi._ratings_all.exists()  # Even replies.
        assert not user_multi.collections.exists()
        assert user_multi._ratings_all(manager='unfiltered_for_relations').exists()
        assert user_multi.collections(manager='unfiltered_for_relations').exists()

        banned_content = user_sole.content_disabled_on_ban
        self.assertQuerySetContentsEqual(
            banned_content.ratings(manager='unfiltered_for_relations').all(),
            user_sole._ratings_all(manager='unfiltered_for_relations').all(),
        )
        # User was not removed from add-ons - they only had the one where they
        # were a solo author, so they keep the relationship but the add-on is
        # disabled.
        assert banned_content.addons.get() == addon_sole
        assert not banned_content.addons_users(
            manager='unfiltered_for_relations'
        ).exists()
        assert (
            banned_content.collections(manager='unfiltered_for_relations').get()
            == Collection.unfiltered.filter(author=user_sole).get()
        )
        assert banned_content.picture_type == 'image/png'
        assert banned_content.picture_backup_name == (
            # Generated by our mock above - real one would be a hexdigest hash
            f'{user_sole.pk}_original.png'
        )

        banned_content = user_multi.content_disabled_on_ban
        self.assertQuerySetContentsEqual(
            banned_content.ratings(manager='unfiltered_for_relations').all(),
            user_multi._ratings_all(manager='unfiltered_for_relations').all(),
        )
        # User was removed from add-ons - they only had one where they were an
        # author amongst others, so they were removed from it but the add-on
        # wasn't banned.
        assert not banned_content.addons.exists()
        assert (
            banned_content.addons_users(manager='unfiltered_for_relations').get()
            == addon_multi.addonuser_set(manager='unfiltered_for_relations')
            .filter(user=user_multi)
            .get()
        )
        assert (
            banned_content.collections(manager='unfiltered_for_relations').get()
            == Collection.unfiltered.filter(author=user_multi).get()
        )
        assert banned_content.picture_type == 'image/png'
        assert banned_content.picture_backup_name == (
            # Generated by our mock above - real one would be a hexdigest hash
            f'{user_multi.pk}_original.png'
        )

        assert not self.storage.exists(user_sole.picture_path)
        assert not self.storage.exists(user_sole.picture_path_original)
        assert not self.storage.exists(user_multi.picture_path)
        assert not self.storage.exists(user_multi.picture_path_original)

        assert user_sole.deleted
        self.assertCloseToNow(user_sole.banned)
        self.assertCloseToNow(user_sole.modified)
        assert user_sole.email == 'sole@foo.baa'
        assert user_sole.auth_id is None
        assert user_sole.fxa_id == '13579'
        assert user_sole.last_login_ip == '127.0.0.1'
        assert user_sole.averagerating == 4.4
        assert user_sole.biography == 'ban me'
        assert user_sole.bypass_upload_restrictions
        assert user_sole.location == 'some where'
        assert user_sole.occupation == 'some job'
        assert user_sole.read_dev_agreement

        assert user_multi.deleted
        self.assertCloseToNow(user_multi.banned)
        self.assertCloseToNow(user_multi.modified)
        assert user_multi.email == 'multi.addons@foo.baa'
        assert user_multi.auth_id is None
        assert user_multi.fxa_id == '24680'
        assert user_multi.last_login_ip == '127.0.0.2'
        assert user_multi.averagerating == 2.2
        assert user_multi.biography == 'ban me too'
        assert user_multi.bypass_upload_restrictions
        assert user_multi.location == 'some where too'
        assert user_multi.occupation == 'some job too'
        assert user_multi.read_dev_agreement

        assert not user_innocent.deleted
        assert not user_innocent.banned
        assert user_innocent.auth_id
        assert user_innocent.ratings.exists()
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user_innocent.email
        ).exists()

        assert (
            EmailUserRestriction.objects.filter(
                email_pattern='multiaddons@foo.baa',  # Normalized
            ).count()
            == 2
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern='multiaddons@foo.baa',  # Normalized
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {user_multi.pk} ban'
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern='multiaddons@foo.baa',  # Normalized
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {user_multi.pk} ban'
        )

        assert (
            EmailUserRestriction.objects.filter(email_pattern=user_sole.email).count()
            == 2
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=user_sole.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).get()
        assert restriction.reason == 'Already exists'
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=user_sole.email,
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {user_sole.pk} ban'
        )

        return {
            'user_innocent': user_innocent,
            'user_sole': user_sole,
            'user_multi': user_multi,
        }

    @mock.patch('olympia.users.models.download_file_contents_from_backup_storage')
    @mock.patch('olympia.users.models.backup_storage_enabled', lambda: True)
    def test_unban_and_restore_banned_content(
        self, download_file_contents_from_backup_storage_mock
    ):
        download_file_contents_from_backup_storage_mock.side_effect = (
            lambda remote_path: f'Fake content from {remote_path}'.encode('utf-8')
        )
        fake_admin = user_factory(display_name='Fake Admin')
        core.set_user(fake_admin)  # Needed for activity log
        users = self.test_ban_and_disable_related_content_bulk()
        user_sole = users['user_sole']
        user_multi = users['user_multi']
        assert BannedUserContent.objects.filter(user=user_sole).exists()
        assert BannedUserContent.objects.filter(user=user_multi).exists()

        UserProfile.objects.filter(
            pk__in=(user_sole.pk, user_multi.pk)
        ).unban_and_reenable_related_content()

        # user_sole was unbanned and content was restored.
        user_sole.reload()
        assert not user_sole.banned
        assert not user_sole.deleted
        addon_sole = user_sole.addons.get()
        assert addon_sole.status == amo.STATUS_APPROVED
        assert user_sole._ratings_all.all().count() == 2  # Includes replies
        assert user_sole.collections.count() == 1
        assert not BannedUserContent.objects.filter(user=user_sole).exists()

        # user_multi was unbanned and content was restored.
        user_multi.reload()
        assert not user_multi.banned
        assert not user_multi.deleted
        assert user_multi.addons.count() == 1
        assert user_multi._ratings_all.count() == 2  # Includes replies
        assert user_multi.collections.count() == 1

        for action in (
            amo.LOG.ADMIN_USER_CONTENT_RESTORED,
            amo.LOG.ADMIN_USER_UNBAN,
        ):
            assert (
                ActivityLog.objects.filter(action=action.id, user=fake_admin).count()
                == 2
            )
            assert {
                activity.arguments[0]
                for activity in ActivityLog.objects.filter(
                    action=action.id, user=fake_admin
                )
            } == {user_multi, user_sole}

        assert download_file_contents_from_backup_storage_mock.call_count == 2

        assert self.storage.exists(user_sole.picture_path_original)
        assert self.storage.exists(user_multi.picture_path_original)
        # We didn't use a real image in order to distinguish between the 2
        # users so skip checking the resized version (picture_path), it's
        # tested in another test below.

        # We shouldn't have any email restrictions left.
        assert not EmailUserRestriction.objects.exists()

    @mock.patch('olympia.users.models.download_file_contents_from_backup_storage')
    @mock.patch('olympia.users.models.backup_storage_enabled', lambda: True)
    def test_unban_and_restore_banned_content_single(
        self, download_file_contents_from_backup_storage_mock
    ):
        download_file_contents_from_backup_storage_mock.return_value = (
            get_uploaded_file('preview_4x3.jpg').read()
        )
        fake_admin = user_factory(display_name='Fake Admin')
        core.set_user(fake_admin)  # Needed for activity log
        users = self.test_ban_and_disable_related_content_bulk()
        user_sole = users['user_sole']
        user_multi = users['user_multi']
        assert BannedUserContent.objects.filter(user=user_sole).exists()
        assert BannedUserContent.objects.filter(user=user_multi).exists()

        UserProfile.objects.filter(pk=user_sole.pk).unban_and_reenable_related_content()

        # user_sole was unbanned and content was restored.
        user_sole.reload()
        assert not user_sole.banned
        assert not user_sole.deleted
        addon_sole = user_sole.addons.get()
        assert addon_sole.status == amo.STATUS_APPROVED
        assert user_sole._ratings_all.all().count() == 2  # Includes replies
        assert user_sole.collections.count() == 1
        assert not BannedUserContent.objects.filter(user=user_sole).exists()
        activity = ActivityLog.objects.filter(
            action=amo.LOG.ADMIN_USER_CONTENT_RESTORED.id
        ).latest('pk')
        assert activity.arguments == [user_sole]
        assert activity.user == fake_admin
        assert self.storage.exists(user_sole.picture_path_original)
        assert self.storage.exists(user_sole.picture_path)

        # We shouldn't have any email restrictions left for the unbanned user.
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user_sole.email
        ).exists()

        # user_multi was not touched.
        user_multi.reload()
        assert user_multi.deleted
        assert user_multi.banned
        assert BannedUserContent.objects.filter(user=user_multi).exists()
        assert user_multi.collections.count() == 0
        assert user_multi.ratings.count() == 0
        assert user_multi.addons.count() == 0
        assert not (
            ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_CONTENT_RESTORED.id)
            .exclude(pk=activity.pk)
            .exists()
        )
        assert not self.storage.exists(user_multi.picture_path_original)
        assert not self.storage.exists(user_multi.picture_path)

        # We should still have any email restrictions left for the banned user,
        # with normalized email.
        assert EmailUserRestriction.objects.filter(
            email_pattern='multiaddons@foo.baa'
        ).exists()

    @mock.patch('olympia.users.models.download_file_contents_from_backup_storage')
    @mock.patch('olympia.users.models.backup_storage_enabled', lambda: False)
    def test_no_restoring_avatar_without_backup_storage_enabled(
        self, download_file_contents_from_backup_storage_mock
    ):
        user = user_factory(banned=self.days_ago(1), deleted=True)
        BannedUserContent.objects.create(
            user=user, picture_type='image/png', picture_backup_name='whatever.png'
        )
        UserProfile.objects.filter(pk=user.pk).unban_and_reenable_related_content()
        user.reload()
        assert not user.picture_type
        assert download_file_contents_from_backup_storage_mock.call_count == 0

    def setup_user_to_be_have_content_disabled(self, user):
        addon = user.addons.last()

        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with self.storage.open(user.picture_path, 'wb') as fobj:
            fobj.write(b'test data\n')

        with self.storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write(b'original test data\n')

        assert user.addons.count() == 1
        rating = Rating.objects.create(
            user=user, addon=addon, version=addon.current_version
        )
        Rating.objects.create(
            user=user, addon=addon, version=addon.current_version, reply_to=rating
        )
        Collection.objects.create(author=user)

    def test_delete_with_related_content_exclude_addons_with_other_devs(self):
        from olympia.addons.models import update_search_index

        user = UserProfile.objects.get(pk=55021)
        addon = user.addons.last()
        self.setup_user_to_be_have_content_disabled(user)
        AddonUser.objects.create(addon=addon, user=user_factory())

        # Now that everything is set up, disable/delete related content.
        update_search_index.reset_mock()
        user.delete()
        update_search_index.assert_called_with(sender=AddonUser, instance=addon)

        # The add-on status should not have been touched, it has another dev.
        assert not user.addons.exists()
        addon.reload()
        assert addon.status == amo.STATUS_APPROVED

        assert not user._ratings_all.exists()  # Even replies.
        assert not user.collections.exists()

        assert not self.storage.exists(user.picture_path)
        assert not self.storage.exists(user.picture_path_original)

    def test_delete_with_just_addon_with_other_devs(self):
        from olympia.addons.models import update_search_index

        user = UserProfile.objects.get(pk=55021)
        addon = user.addons.last()
        AddonUser.objects.create(addon=addon, user=user_factory())

        # Now that everything is set up, disable/delete related content.
        update_search_index.reset_mock()
        user.delete()
        update_search_index.assert_called_with(sender=AddonUser, instance=addon)

        # The add-on should not have been touched, it has another dev.
        assert not user.addons.exists()
        addon.reload()
        assert addon.status == amo.STATUS_APPROVED

    def test_delete_with_related_content_actually_delete(self):
        addon = Addon.objects.latest('pk')
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with self.storage.open(user.picture_path, 'wb') as fobj:
            fobj.write(b'test data\n')

        with self.storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write(b'original test data\n')

        assert user.addons.count() == 1
        rating = Rating.objects.create(
            user=user, addon=addon, version=addon.current_version
        )
        Rating.objects.create(
            user=user, addon=addon, version=addon.current_version, reply_to=rating
        )
        Collection.objects.create(author=user)

        # Now that everything is set up, delete related content.
        user.delete()

        assert not user.addons.exists()

        assert not user._ratings_all.exists()  # Even replies.
        assert not user.collections.exists()

        assert not self.storage.exists(user.picture_path)
        assert not self.storage.exists(user.picture_path_original)

    def test_delete_picture(self):
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with self.storage.open(user.picture_path, 'wb') as fobj:
            fobj.write(b'test data\n')

        with self.storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write(b'original test data\n')

        user.delete_picture()

        user.reload()
        assert user.picture_type is None
        assert not self.storage.exists(user.picture_path)
        assert not self.storage.exists(user.picture_path_original)

    def test_groups_list(self):
        user = UserProfile.objects.get(pk=55021)
        group1 = Group.objects.create(name='un')
        group2 = Group.objects.create(name='deux')
        GroupUser.objects.create(user=user, group=group1)
        GroupUser.objects.create(user=user, group=group2)
        assert user.groups_list == list(user.groups.all())
        assert len(user.groups_list) == 2

        # Remove the user from one of the groups, groups_list should not have
        # changed since it's a cached property.
        GroupUser.objects.filter(group=group1).delete()
        assert len(user.groups_list) == 2

        # Delete the cached property, it should be updated.
        del user.groups_list
        assert len(user.groups_list) == 1
        assert user.groups_list == [group2]

    def test_welcome_name(self):
        u1 = UserProfile.objects.create(username='sc')
        u2 = UserProfile.objects.create(username='sc2', display_name='Sarah Connor')
        u3 = UserProfile.objects.create()
        assert u1.welcome_name == 'Firefox user %s' % u1.id
        assert u2.welcome_name == 'Sarah Connor'
        assert u3.welcome_name == 'Firefox user %s' % u3.id

    def test_welcome_name_anonymous(self):
        user = UserProfile.objects.create(
            username='anonymous-bb4f3cbd422e504080e32f2d9bbfcee0', id=1234
        )
        assert user.welcome_name == 'Firefox user 1234'

    def test_welcome_name_anonymous_with_display(self):
        user = UserProfile.objects.create(display_name='John Connor')
        user.username = get_anonymized_username()
        assert user.welcome_name == 'John Connor'

    def test_has_anonymous_username_no_names(self):
        user = UserProfile.objects.create(display_name=None)
        user.username = get_anonymized_username()
        assert user.has_anonymous_username

    def test_has_anonymous_username_username_set(self):
        user = UserProfile.objects.create(username='bob', display_name=None)
        assert not user.has_anonymous_username

    def test_has_anonymous_username_display_name_set(self):
        user = UserProfile.objects.create(display_name='Bob Bobbertson')
        user.username = get_anonymized_username()
        assert user.has_anonymous_username

    def test_has_anonymous_username_both_names_set(self):
        user = UserProfile.objects.create(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_username

    def test_has_anonymous_display_name_no_names(self):
        user = UserProfile.objects.create(display_name=None)
        user.username = get_anonymized_username()
        assert user.has_anonymous_display_name

    def test_has_anonymous_display_name_username_set(self):
        user = UserProfile.objects.create(username='bob', display_name=None)
        assert user.has_anonymous_display_name

    def test_has_anonymous_display_name_display_name_set(self):
        user = UserProfile.objects.create(display_name='Bob Bobbertson')
        user.username = get_anonymized_username()
        assert not user.has_anonymous_display_name

    def test_has_anonymous_display_name_both_names_set(self):
        user = UserProfile.objects.create(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_display_name

    def test_superuser(self):
        user = UserProfile.objects.get(pk=9946)
        assert not user.is_staff
        assert not user.is_superuser

        # Give the user '*:*'
        # (groups_list cached_property is automatically cleared because we're
        #  creating a GroupUser instance).
        group = Group.objects.filter(rules='*:*').get()
        GroupUser.objects.create(group=group, user=user)
        assert not user.is_staff
        assert user.is_superuser

        user.update(email='employee@mozilla.com')
        assert user.is_staff
        assert user.is_superuser

        # No extra queries are made to check a second time, thanks to
        # groups_list being a cached_property.
        with self.assertNumQueries(0):
            assert user.is_superuser

    def test_staff_only(self):
        group = Group.objects.create(
            name='Admins of Something', rules='Admin:Something'
        )
        user = UserProfile.objects.get(pk=9946)
        assert not user.is_staff
        assert not user.is_superuser

        # Even as part of an Admin:* group, the user is still not considered
        # 'staff'.
        GroupUser.objects.create(group=group, user=user)
        assert not user.is_staff
        assert not user.is_superuser

        # Now that they have a mozilla.com email, they are.
        user.update(email='employee@mozilla.com')
        assert user.is_staff
        assert not user.is_superuser

    def test_give_and_then_remove_admin_powers(self):
        group = Group.objects.create(name='Admins', rules='*:*')
        user = UserProfile.objects.get(pk=9946)
        relation = GroupUser.objects.create(group=group, user=user)
        relation.delete()
        assert not user.is_staff
        assert not user.is_superuser

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile.objects.create(
            id=1234, picture_type='image/png', modified=date.today(), username='a'
        )
        u.picture_url.index('/userpics/34/1234/1234/1234.png?modified=')

        u = UserProfile.objects.create(
            id=1234567890, picture_type='image/png', modified=date.today(), username='b'
        )
        u.picture_url.index('/userpics/90/7890/1234567890/1234567890.png?modified=')

        u = UserProfile.objects.create(id=123456, picture_type=None, username='c')
        assert u.picture_url.endswith('/anon_user.png')

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original ratings.
        """
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=2519)
        version = addon.find_latest_public_listed_version()
        new_rating = Rating(
            version=version, user=user, rating=2, body='hello', addon=addon
        )
        new_rating.save()
        new_reply = Rating(
            version=version,
            user=user,
            reply_to=new_rating,
            addon=addon,
            body='my reply',
        )
        new_reply.save()

        review_list = [rating.pk for rating in user.ratings]

        assert len(review_list) == 1
        assert new_rating.pk in review_list, (
            'Original review must show up in ratings list.'
        )
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in ratings list.'
        )

    def test_num_addons_listed(self):
        """Test that num_addons_listed is only considering add-ons for which
        the user is marked as listed, and that only public and listed add-ons
        are counted."""
        user = UserProfile.objects.get(id=2519)
        addon = Addon.objects.get(pk=3615)
        AddonUser.objects.create(addon=addon, user=user, listed=True)
        assert user.num_addons_listed == 1

        extra_addon = addon_factory(status=amo.STATUS_NOMINATED)
        AddonUser.objects.create(addon=extra_addon, user=user, listed=True)
        extra_addon2 = addon_factory()
        AddonUser.objects.create(addon=extra_addon2, user=user, listed=True)
        self.make_addon_unlisted(extra_addon2)
        assert user.num_addons_listed == 1

        AddonUser.objects.filter(addon=addon, user=user).update(listed=False)
        assert user.num_addons_listed == 0

    def test_my_addons(self):
        """Test helper method to get N addons."""
        addon1 = Addon.objects.create(name='test-1', type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon_id=addon1.id, user_id=2519, listed=True)
        addon2 = Addon.objects.create(name='test-2', type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon_id=addon2.id, user_id=2519, listed=True)
        addons = UserProfile.objects.get(id=2519).my_addons()
        assert sorted(str(a.name) for a in addons) == [addon1.name, addon2.name]

    def test_get_url_path(self):
        assert UserProfile.objects.create(id=1).get_url_path() == (
            '/en-US/firefox/user/1/'
        )
        assert UserProfile.objects.create(username='yolo', id=2).get_url_path() == (
            '/en-US/firefox/user/2/'
        )

    def test_cannot_set_password(self):
        user = UserProfile.objects.get(id='4043307')
        with self.assertRaises(NotImplementedError):
            user.set_password('password')

    def test_cannot_check_password(self):
        user = UserProfile.objects.get(id='4043307')
        with self.assertRaises(NotImplementedError):
            user.check_password('password')

    def test_get_session_auth_hash(self):
        user = UserProfile.objects.get(id=4043307)
        user.update(auth_id=None)
        assert user.get_session_auth_hash() is None

        user.update(auth_id=12345)
        hash1 = user.get_session_auth_hash()
        assert hash1

        user.update(auth_id=67890)
        hash2 = user.get_session_auth_hash()
        assert hash1 != hash2

        user.update(deleted=True)
        assert user.get_session_auth_hash() is None

    def test_has_read_developer_agreement(self):
        set_config('last_dev_agreement_change_date', '2019-06-12 00:00')
        after_change = datetime(2019, 6, 12) + timedelta(days=1)
        before_change = datetime(2019, 6, 12) - timedelta(days=42)

        assert not UserProfile.objects.create(
            username='a'
        ).has_read_developer_agreement()
        assert not UserProfile.objects.create(
            username='b', read_dev_agreement=None
        ).has_read_developer_agreement()
        assert not UserProfile.objects.create(
            username='c', read_dev_agreement=before_change
        ).has_read_developer_agreement()

        # User has read the agreement after it was modified for
        # post-review: it should return True.
        assert UserProfile.objects.create(
            username='d', read_dev_agreement=after_change
        ).has_read_developer_agreement()

    def test_has_full_profile(self):
        user = UserProfile.objects.get(id=4043307)
        assert not user.addonuser_set.exists()
        assert not user.has_full_profile

        addon = Addon.objects.get(pk=3615)
        addon_user = addon.addonuser_set.create(user=user)
        assert user.has_full_profile

        # Only developer and owner roles make a developer profile.
        addon_user.update(role=amo.AUTHOR_ROLE_DEV)
        assert user.has_full_profile
        addon_user.update(role=amo.AUTHOR_ROLE_OWNER)
        assert user.has_full_profile
        # But only if they're listed
        addon_user.update(role=amo.AUTHOR_ROLE_OWNER, listed=False)
        assert not user.has_full_profile
        addon_user.update(listed=True)
        assert user.has_full_profile
        addon_user.update(role=amo.AUTHOR_ROLE_DEV, listed=False)
        assert not user.has_full_profile
        addon_user.update(listed=True)
        assert user.has_full_profile

        # The add-on needs to be public.
        self.make_addon_unlisted(addon)  # Easy way to toggle status
        assert not user.reload().has_full_profile
        self.make_addon_listed(addon)
        addon.update(status=amo.STATUS_APPROVED)
        assert user.reload().has_full_profile

        addon.delete()
        assert not user.reload().has_full_profile

    def test_get_lookup_field(self):
        user = UserProfile.objects.get(id=55021)
        lookup_field_pk = UserProfile.get_lookup_field(str(user.id))
        assert lookup_field_pk == 'pk'
        lookup_field_email = UserProfile.get_lookup_field(user.email)
        assert lookup_field_email == 'email'
        lookup_field_random_digit = UserProfile.get_lookup_field('123456')
        assert lookup_field_random_digit == 'pk'
        lookup_field_random_string = UserProfile.get_lookup_field('my@mail.co')
        assert lookup_field_random_string == 'email'

    def test_suppressed_email(self):
        user = user_factory()
        assert not user.suppressed_email

        suppressed_email = SuppressedEmail.objects.create(email=user.email)

        assert user.reload().suppressed_email == suppressed_email

    def test_email_verification(self):
        user = user_factory()
        assert not user.email_verification

        verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(email=user.email)
        )

        assert user.reload().email_verification.id == verification.id

    def test_is_survey_eligible(self):
        user = user_factory()
        addon = addon_factory(users=[user])
        survey_id = amo.DEV_EXP_SURVEY_ALCHEMER_ID

        with self.assertRaises(ValueError):
            user.is_survey_eligible(123)

        # 1. addon updated >30 days ago
        addon.last_updated = timezone.now() - timedelta(days=31)
        addon.save()
        assert not user.is_survey_eligible(survey_id)

        # 2. addon updated <30 days ago, no survey response
        addon.last_updated = timezone.now() - timedelta(days=29)
        addon.save()
        assert user.is_survey_eligible(amo.DEV_EXP_SURVEY_ALCHEMER_ID)

        # 3. addon updated <30 days ago, survey response
        instance = SurveyResponse.objects.create(user=user, survey_id=survey_id)
        assert not user.is_survey_eligible(amo.DEV_EXP_SURVEY_ALCHEMER_ID)

        # 4. addon updated <30 days ago, survey response >180 days ago
        instance.date_responded = timezone.now() - timedelta(days=181)
        instance.save()
        assert user.is_survey_eligible(amo.DEV_EXP_SURVEY_ALCHEMER_ID)


class TestIPNetworkUserRestriction(TestCase):
    def test_str(self):
        obj = IPNetworkUserRestriction.objects.create(network='192.168.1.0/24')
        assert str(obj) == '192.168.1.0/24'

    def test_allowed_ip4_address(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = user_factory(last_login_ip='192.168.0.5')
        IPNetworkUserRestriction.objects.create(network='192.168.1.0/28')
        assert IPNetworkUserRestriction.allow_submission(request)

        request = RequestFactory(REMOTE_ADDR='10.8.0.1').get('/')
        request.user = user_factory(last_login_ip='10.8.0.1')
        IPNetworkUserRestriction.objects.create(network='10.8.0.0/32')
        assert IPNetworkUserRestriction.allow_submission(request)

    def test_blocked_ip4_32_subnet(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.8').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='192.168.0.8/32')
        assert not IPNetworkUserRestriction.allow_submission(request)

    def test_allowed_ip4_28_subnet(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.254').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='192.168.0.0/28')
        assert IPNetworkUserRestriction.allow_submission(request)

    def test_blocked_ip4_24_subnet(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.254').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='192.168.0.0/24')
        assert not IPNetworkUserRestriction.allow_submission(request)

    def test_blocked_ip4_address(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='192.168.0.0/28')
        assert not IPNetworkUserRestriction.allow_submission(request)

        request = RequestFactory(REMOTE_ADDR='10.8.0.1').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='10.8.0.0/28')
        assert not IPNetworkUserRestriction.allow_submission(request)

    def test_ip4_address_validated(self):
        with pytest.raises(forms.ValidationError) as exc_info:
            IPNetworkUserRestriction(network='127.0.0.1/1218').full_clean()
        assert exc_info.value.messages[0] == (
            "'127.0.0.1/1218' does not appear to be an IPv4 or IPv6 network"
        )

    def test_ip6_address_validated(self):
        with pytest.raises(forms.ValidationError) as exc_info:
            IPNetworkUserRestriction(network='::1/1218').full_clean()
        assert exc_info.value.messages[0] == (
            "'::1/1218' does not appear to be an IPv4 or IPv6 network"
        )

    def test_blocked_user_login_ip(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.8').get('/')
        request.user = user_factory(last_login_ip='192.168.1.1')
        IPNetworkUserRestriction.objects.create(network='192.168.1.1/32')
        assert not IPNetworkUserRestriction.allow_submission(request)

    def test_allowed_approval_while_blocking_submission(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = user_factory(last_login_ip='10.0.0.1')
        IPNetworkUserRestriction.objects.create(network='192.168.0.0/28')
        # Submission is not allowed.
        assert not IPNetworkUserRestriction.allow_submission(request)
        # Approval is.
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert IPNetworkUserRestriction.allow_auto_approval(upload)

    def test_blocked_approval_last_login_ip(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = user_factory(last_login_ip='192.168.0.1')
        IPNetworkUserRestriction.objects.create(
            network='192.168.0.0/28', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        # Submission remains allowed.
        assert IPNetworkUserRestriction.allow_submission(request)
        # Approval is blocked even though it was with a different ip, because
        # of the user last_login_ip.
        upload = FileUpload.objects.create(
            ip_address='192.168.1.2',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert not IPNetworkUserRestriction.allow_auto_approval(upload)

    def test_blocked_approval_while_allowing_submission(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = user_factory(last_login_ip='10.0.0.1')
        IPNetworkUserRestriction.objects.create(
            network='192.168.0.0/28', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        # Submission remains allowed.
        assert IPNetworkUserRestriction.allow_submission(request)
        # Approval is blocked.
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert not IPNetworkUserRestriction.allow_auto_approval(upload)

    def test_network_from_ip(self):
        assert IPNetworkUserRestriction.network_from_ip('192.168.0.1') == IPv4Network(
            '192.168.0.1/32'
        )
        assert IPNetworkUserRestriction.network_from_ip(
            '2001:0db8:85a3:0000:0000:8a2e:0370:7334'
        ) == IPv6Network('2001:0db8:85a3::/64')

    def test_network_from_ip_blank(self):
        with self.assertRaises(ValueError):
            IPNetworkUserRestriction.network_from_ip(None)
        with self.assertRaises(ValueError):
            IPNetworkUserRestriction.network_from_ip('')


class TestDisposableEmailDomainRestriction(TestCase):
    def test_email_allowed(self):
        DisposableEmailDomainRestriction.objects.create(domain='bar.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='bar@foo.com')
        assert DisposableEmailDomainRestriction.allow_submission(request)

    def test_email_domain_blocked(self):
        DisposableEmailDomainRestriction.objects.create(domain='bar.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@bar.com')
        assert not DisposableEmailDomainRestriction.allow_submission(request)

    def test_user_somehow_not_authenticated(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        assert not DisposableEmailDomainRestriction.allow_submission(request)

    def test_blocked_approval(self):
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@bar.com')
        DisposableEmailDomainRestriction.objects.create(
            domain='bar.com', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        # Submission remains allowed.
        assert DisposableEmailDomainRestriction.allow_submission(request)
        # Approval is blocked.
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert not DisposableEmailDomainRestriction.allow_auto_approval(upload)

    def test_allowed_approval(self):
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@bar.com')
        DisposableEmailDomainRestriction.objects.create(domain='bar.com')
        # Submission is blocked.
        assert not DisposableEmailDomainRestriction.allow_submission(request)
        # Approval is allowed.
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert DisposableEmailDomainRestriction.allow_auto_approval(upload)


class TestEmailUserRestriction(TestCase):
    def test_str(self):
        obj = EmailUserRestriction.objects.create(email_pattern='fôo@bar.com')
        assert str(obj) == 'fôo@bar.com'

    def test_get_or_create_normalization(self):
        obj, created = EmailUserRestriction.objects.get_or_create(
            email_pattern='foo+something@bar.com'
        )
        assert created
        assert obj.email_pattern == 'foo@bar.com'

        obj, created = EmailUserRestriction.objects.get_or_create(
            email_pattern='foo@bar.com'
        )
        assert not created
        assert obj.email_pattern == 'foo@bar.com'

        obj, created = EmailUserRestriction.objects.get_or_create(
            email_pattern='foo+else@bar.com'
        )
        assert not created
        assert obj.email_pattern == 'foo@bar.com'

        obj, created = EmailUserRestriction.objects.get_or_create(
            email_pattern='different@bar.com'
        )
        assert created
        assert obj.email_pattern == 'different@bar.com'

    def test_email_allowed(self):
        EmailUserRestriction.objects.create(email_pattern='foo@bar.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='bar@foo.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    def test_restricted_email(self):
        EmailUserRestriction.objects.create(email_pattern='foo@bar.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@bar.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        request.user.update(email='foo+something@bar.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        request.user.update(email='f.oo+else@bar.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        request.user.update(email='foo.different+something@bar.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    def test_user_somehow_not_authenticated(self):
        EmailUserRestriction.objects.create(email_pattern='foo@bar.com')
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        assert not EmailUserRestriction.allow_submission(request)

    def test_blocked_subdomain(self):
        EmailUserRestriction.objects.create(email_pattern='*@faz.bar.com')

        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@faz.bar.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        request.user = user_factory(email='foo@raz.bar.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    def test_blocked_subdomain_but_allow_parent(self):
        EmailUserRestriction.objects.create(email_pattern='*.mail.com')

        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@faz.mail.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        # We only block a subdomain pattern
        request.user = user_factory(email='foo@mail.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

        # Which also allows similar domains to work
        request.user = user_factory(email='foo@gmail.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    def test_normalize_email_pattern_on_save(self):
        eur = EmailUserRestriction.objects.create(email_pattern='u.s.e.r@example.com')

        assert eur.email_pattern == 'user@example.com'

    def test_blocked_approval(self):
        EmailUserRestriction.objects.create(
            email_pattern='*.mail.com',
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@faz.mail.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert not EmailUserRestriction.allow_auto_approval(upload)

    def test_allowed_approval(self):
        EmailUserRestriction.objects.create(email_pattern='*.mail.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='foo@faz.mail.com')
        assert not EmailUserRestriction.allow_submission(request)
        assert not EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=request.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert EmailUserRestriction.allow_auto_approval(upload)


class TestFingerprintRestriction(TestCase):
    def test_str(self):
        obj = FingerprintRestriction(ja4='t13d1517h2_8daaf6152771_f0fc7018f8e8')
        assert str(obj) == 't13d1517h2_8daaf6152771_f0fc7018f8e8'

    def test_no_ja4_submission_allowed(self):
        FingerprintRestriction.objects.create(
            ja4='t13d1517h2_8daaf6152771_f0fc7018f8e8'
        )
        request = RequestFactory().get('/')
        assert FingerprintRestriction.allow_submission(request)

    def test_no_ja4_auto_approval_allowed(self):
        FingerprintRestriction.objects.create(
            ja4='t13d1517h2_8daaf6152771_f0fc7018f8e8'
        )
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=user_factory(),
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        assert FingerprintRestriction.allow_auto_approval(upload)

    def test_ja4_submission_restricted(self):
        restricted_ja4 = 'some_fake_ja4'
        FingerprintRestriction.objects.create(ja4=restricted_ja4)
        request = RequestFactory().get('/', headers={'Client-JA4': restricted_ja4})
        assert not FingerprintRestriction.allow_submission(request)

    def test_ja4_rating_restriction(self):
        restricted_ja4 = 'some_fake_ja4'
        FingerprintRestriction.objects.create(
            ja4=restricted_ja4, restriction_type=RESTRICTION_TYPES.RATING
        )

        # Submissions are not restricted.
        request = RequestFactory().get('/', headers={'Client-JA4': restricted_ja4})
        assert FingerprintRestriction.allow_submission(request)
        assert not FingerprintRestriction.allow_rating(request)

    def test_ja4_auto_approval_restricted(self):
        restricted_ja4 = 'some_fake_ja4'
        FingerprintRestriction.objects.create(
            ja4=restricted_ja4, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )

        # Submissions or ratings are not restricted.
        request = RequestFactory().get('/', headers={'Client-JA4': restricted_ja4})
        assert FingerprintRestriction.allow_submission(request)
        assert FingerprintRestriction.allow_rating(request)
        assert FingerprintRestriction.allow_rating_without_moderation(request)

        # Auto-approval is restricted.
        upload = FileUpload.objects.create(
            ip_address='192.168.0.1',
            user=user_factory(),
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
            request_metadata={'Client-JA4': restricted_ja4},
        )
        assert not FingerprintRestriction.allow_auto_approval(upload)

    def test_ja4_different_restriction(self):
        restricted_ja4 = 'some_fake_ja4'
        FingerprintRestriction.objects.create(ja4=restricted_ja4)
        request = RequestFactory().get('/', headers={'Client-JA4': 'another_ja4'})
        assert FingerprintRestriction.allow_submission(request)


@override_settings(
    REPUTATION_SERVICE_URL='https://reputation.example.com',
    REPUTATION_SERVICE_TOKEN='fancy_token',
    REPUTATION_SERVICE_TIMEOUT=1.0,
)
class TestIPReputationRestriction(TestCase):
    expected_url = 'https://reputation.example.com/type/ip/192.168.0.1'
    restriction_class = IPReputationRestriction

    @override_settings(REPUTATION_SERVICE_URL=None)
    def test_allowed_reputation_service_url_not_configured(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 0

    @override_settings(REPUTATION_SERVICE_TOKEN=None)
    def test_allowed_reputation_service_token_not_configured(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 0

    @override_settings(REPUTATION_SERVICE_TIMEOUT=None)
    def test_allowed_reputation_service_timeout_not_configured(self):
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 0

    def test_allowed_response_not_200(self):
        responses.add(responses.GET, self.expected_url, status=404)
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url

    def test_allowed_reputation_threshold(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            json={'reputation': 100},
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url

    def test_blocked_reputation_threshold(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            json={'reputation': 45},
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert not self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url

    def test_allowed_valueerror(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            body='garbage',
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url

    def test_allowed_valueerror_but_valid_json(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            json={'reputation': 'garbage'},
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url

    def test_allowed_keyerror(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            json={'no_reputation_oh_noes': 'garbage'},
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='foo@bar.com')

        assert self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url


class TestEmailReputationRestriction(TestIPReputationRestriction):
    expected_url = 'https://reputation.example.com/type/email/foo@bar.com'
    restriction_class = EmailReputationRestriction

    def test_blocked_reputation_threshold_email_variant(self):
        responses.add(
            responses.GET,
            self.expected_url,
            content_type='application/json',
            json={'reputation': 45},
        )
        request = RequestFactory(REMOTE_ADDR='192.168.0.1').get('/')
        request.user = UserProfile(email='f.oo+something@bar.com')

        # Still blocked as if it was foo@bar.com
        assert not self.restriction_class.allow_submission(request)
        assert len(responses.calls) == 1
        http_call = responses.calls[0].request
        assert http_call.headers['Authorization'] == 'APIKey fancy_token'
        assert http_call.url == self.expected_url


class TestUserEmailField(TestCase):
    fixtures = ['base/user_2519']

    def test_success(self):
        user = UserProfile.objects.get(pk=2519)
        assert (
            UserEmailField(queryset=UserProfile.objects.all()).clean(user.email) == user
        )

    def test_failure(self):
        with pytest.raises(forms.ValidationError):
            UserEmailField(queryset=UserProfile.objects.all()).clean('xxx')

    def test_empty_email(self):
        UserProfile.objects.create(email='')
        with pytest.raises(forms.ValidationError) as exc_info:
            UserEmailField(queryset=UserProfile.objects.all()).clean('')

        assert exc_info.value.messages[0] == 'This field is required.'


class TestOnChangeName(TestCase):
    def setUp(self):
        super().setUp()

        # We're in a regular TestCase class so index_addons should have been
        # mocked.
        from olympia.addons.tasks import index_addons

        self.index_addons_mock = index_addons

    def test_changes_display_name_not_a_listed_author(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=False)
        self.index_addons_mock.reset_mock()
        user.update(display_name='bâr')
        assert self.index_addons_mock.delay.call_count == 0

    def test_changes_display_name(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(display_name='bâr')
        assert self.index_addons_mock.delay.call_count == 1
        assert self.index_addons_mock.delay.call_args[0] == ([addon.pk],)

    def test_changes_username(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(username='föo')
        assert self.index_addons_mock.delay.call_count == 1
        assert self.index_addons_mock.delay.call_args[0] == ([addon.pk],)

    @mock.patch('olympia.scanners.tasks.run_narc_on_version')
    def test_change_display_name_narc_enabled(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        user = user_factory()
        addon = addon_factory(users=[user])
        user.update(display_name='Flôp')
        assert run_narc_on_version_mock.delay.call_count == 1
        assert run_narc_on_version_mock.delay.call_args[0] == (
            addon.current_version.pk,
        )

    @mock.patch('olympia.scanners.tasks.run_narc_on_version')
    def test_change_display_name_narc_disabled(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=False)
        user = user_factory()
        addon_factory(users=[user])
        user.update(display_name='Flôp')
        assert run_narc_on_version_mock.delay.call_count == 0

    @mock.patch('olympia.scanners.tasks.run_narc_on_version')
    def test_change_display_name_only_non_mozilla_disabled_addons_current_version(
        self, run_narc_on_version_mock
    ):
        self.create_switch('enable-narc', active=True)
        user = user_factory()
        addon = addon_factory(users=[user])
        addon2 = version_factory(
            addon=addon_factory(users=[user], version_kw={'version': '1.0'}),
            version='2.0',
        ).addon
        addon3 = addon_factory(users=[user])
        version_from_addon3 = addon3.current_version
        addon3.current_version.is_user_disabled = True  # Should still be scanned
        assert not addon3.current_version

        # Add some extra add-ons that are going to be ignored.
        addon_factory(name='Force disabled', users=[user]).force_disable()
        self.make_addon_unlisted(addon_factory(name='Pure unlisted', users=[user]))

        user.update(display_name='Flôp')

        assert run_narc_on_version_mock.delay.call_count == 3
        assert run_narc_on_version_mock.delay.call_args_list[0][0] == (
            addon.current_version.pk,
        )
        assert run_narc_on_version_mock.delay.call_args_list[1][0] == (
            addon2.current_version.pk,
        )
        assert run_narc_on_version_mock.delay.call_args_list[2][0] == (
            version_from_addon3.pk,
        )

    def test_changes_something_else(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(last_login=self.days_ago(0))
        assert self.index_addons_mock.delay.call_count == 0

    @mock.patch('olympia.scanners.tasks.run_narc_on_version')
    def test_changes_something_else_narc_enabled(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        self.test_changes_something_else()
        assert run_narc_on_version_mock.call_count == 0


def find_users(email):
    """
    Given an email find all the possible users, by looking in
    users and in their history.
    """
    return UserProfile.objects.filter(
        models.Q(email=email) | models.Q(history__email=email)
    ).distinct()


class TestUserHistory(TestCase):
    def test_user_history(self):
        user = UserProfile.objects.create(email='foo@bar.com')
        assert user.history.count() == 0
        user.update(email='foopy@barby.com')
        assert user.history.count() == 1
        user.update(email='foopy@barby.com')
        assert user.history.count() == 1

    def test_user_find(self):
        user = UserProfile.objects.create(email='luke@jedi.com')
        # Checks that you can have multiple copies of the same email and
        # that we only get distinct results back.
        user.update(email='dark@sith.com')
        user.update(email='luke@jedi.com')
        user.update(email='dark@sith.com')
        assert [user] == list(find_users('luke@jedi.com'))
        assert [user] == list(find_users('dark@sith.com'))

    def test_user_find_multiple(self):
        user_1 = UserProfile.objects.create(username='user_1', email='luke@jedi.com')
        user_1.update(email='dark@sith.com')
        user_2 = UserProfile.objects.create(username='user_2', email='luke@jedi.com')
        assert [user_1, user_2] == list(find_users('luke@jedi.com'))


class TestUserManager(TestCase):
    fixtures = ('users/test_backends',)

    def test_create_user(self):
        user = UserProfile.objects.create_user('test@test.com', 'xxx')
        assert user.pk is not None

    def test_create_superuser(self):
        user = UserProfile.objects.create_superuser(
            'test',
            'test@test.com',
        )
        assert user.pk is not None
        assert Group.objects.get(name='Admins') in user.groups.all()
        assert not user.is_staff  # Not a mozilla.com email...
        assert user.is_superuser

    def test_get_or_create_service_account(self):
        name = 'some service'

        user = UserProfile.objects.get_or_create_service_account(name=name)

        assert user.pk is not None
        assert not user.email
        assert not user.fxa_id
        assert user.username == 'service-account-some-service'
        assert not user.notes
        assert user.read_dev_agreement is not None
        assert APIKey.get_jwt_key(user=user)

    def test_get_or_create_service_account_with_notes(self):
        name = 'some service'
        notes = 'some notes'

        user = UserProfile.objects.get_or_create_service_account(name=name, notes=notes)

        assert user.pk is not None
        assert not user.email
        assert not user.fxa_id
        assert user.username == 'service-account-some-service'
        assert user.notes == notes
        assert user.read_dev_agreement is not None

    def test_get_or_create_service_account_return_existing_user(self):
        number_of_users = len(UserProfile.objects.all())
        number_of_keys = len(APIKey.objects.all())

        name = 'some service'
        user = UserProfile.objects.get_or_create_service_account(name=name)
        jwt_key = APIKey.get_jwt_key(user=user)
        assert jwt_key
        # Call method again, verify that it doesn't recreate an account.
        user2 = UserProfile.objects.get_or_create_service_account(name=name)
        assert user2.pk == user.pk
        assert APIKey.get_jwt_key(user=user2) == jwt_key

        assert len(UserProfile.objects.all()) == number_of_users + 1
        assert len(APIKey.objects.all()) == number_of_keys + 1

    def test_get_service_account_with_empty_name(self):
        with self.assertRaises(UserProfile.DoesNotExist):
            UserProfile.objects.get_service_account(name='')

    def test_get_unknown_service_account(self):
        with self.assertRaises(UserProfile.DoesNotExist):
            UserProfile.objects.get_service_account(name='unknown')

    def test_get_service_account(self):
        name = 'some service'
        user = UserProfile.objects.get_or_create_service_account(name=name)
        assert UserProfile.objects.get_service_account(name=name) == user


@pytest.mark.django_db
def test_get_session_auth_hash_is_used_for_session_auth():
    user = user_factory()
    client = amo.tests.TestClient()
    assert not client.session.items()
    client.force_login(user)
    assert client.session.items()

    request = RequestFactory().get('/')
    request.session = client.session
    assert get_user(request) == user

    user.update(auth_id=generate_auth_id())
    assert get_user(request) != user


class TestSuppressedEmailVerification(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.suppressed_email = SuppressedEmail.objects.create(email='test@example.com')

    def test_raise_for_duplicate_email_block(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )

        with pytest.raises(IntegrityError):
            SuppressedEmailVerification.objects.create(
                suppressed_email=email_verification.suppressed_email
            )

    def test_deletes_verification_with_block(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )
        self.suppressed_email.delete()
        assert not SuppressedEmailVerification.objects.filter(
            pk=email_verification.pk
        ).exists()

    def test_expiration_thirty_days_after_creation(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )

        expected_expiration_date = email_verification.created + timedelta(days=30)

        assert email_verification.expiration == expected_expiration_date

    def test_default_status(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )

        assert (
            email_verification.status
            == SuppressedEmailVerification.STATUS_CHOICES.Pending
        )

    def test_only_valid_options(self):
        with pytest.raises(ValueError):
            SuppressedEmailVerification.objects.create(
                suppressed_email=self.suppressed_email, status='invalid'
            )

    def test_is_expired(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )
        assert not email_verification.is_expired

        with time_machine.travel(
            email_verification.created + timedelta(days=31), tick=False
        ):
            assert email_verification.is_expired

    def test_is_timedout(self):
        email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )
        assert not email_verification.is_timedout

        with time_machine.travel(
            email_verification.created + timedelta(minutes=10, seconds=1), tick=False
        ):
            assert email_verification.is_timedout
