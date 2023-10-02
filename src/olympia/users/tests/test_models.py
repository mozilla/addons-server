import django  # noqa
from datetime import date, datetime, timedelta
from django import forms
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.db import models
from django.test.client import RequestFactory
from django.test.utils import override_settings
from ipaddress import IPv4Address

import pytest
import responses
from freezegun import freeze_time

import olympia  # noqa
from olympia import amo, core
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.amo.utils import SafeStorage
from olympia.bandwagon.models import Collection
from olympia.files.models import File, FileUpload
from olympia.ratings.models import Rating
from olympia.users.models import (
    RESTRICTION_TYPES,
    DeniedName,
    DisposableEmailDomainRestriction,
    EmailReputationRestriction,
    EmailUserRestriction,
    IPNetworkUserRestriction,
    IPReputationRestriction,
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
        with core.override_remote_addr('4.8.15.16'):
            self.client.force_login(user)
        user.reload()
        assert user.last_login_ip == '4.8.15.16'
        assert ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).count() == 1
        log = ActivityLog.objects.filter(action=amo.LOG.LOG_IN.id).latest('pk')
        assert log.user == user
        assert log.iplog.ip_address_binary == IPv4Address('4.8.15.16')

        with core.override_remote_addr('23.42.42.42'):
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
        assert email.reply_to == ['amo-admins+deleted@mozilla.com']
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

    @freeze_time(amo.MZA_LAUNCH_DATETIME - timedelta(minutes=1), as_arg=True)
    def test_delete_email_says_fxa_before_mza_date_and_mza_after(frozen_time, self):
        user = UserProfile.objects.get(pk=4043307)
        user.delete()
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == [user.email]
        assert 'deleted your Firefox Account.' in email.body

        frozen_time.move_to(amo.MZA_LAUNCH_DATETIME)
        user.update(deleted=False, display_name='somebody')
        mail.outbox.clear()
        user.delete()
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == [user.email]
        assert 'deleted your Mozilla account (we renamed Firefox Accounts' in email.body

    def test_ban_and_disable_related_content_bulk(self):
        user_sole = user_factory(
            email='sole@foo.baa', fxa_id='13579', last_login_ip='127.0.0.1'
        )
        addon_sole = addon_factory(users=[user_sole])
        self.setup_user_to_be_have_content_disabled(user_sole)
        user_multi = user_factory(
            email='multi@foo.baa', fxa_id='24680', last_login_ip='127.0.0.2'
        )
        innocent_user = user_factory()
        addon_multi = addon_factory(
            users=UserProfile.objects.filter(id__in=[user_multi.id, innocent_user.id])
        )
        self.setup_user_to_be_have_content_disabled(user_multi)

        # Now that everything is set up, disable/delete related content.
        UserProfile.ban_and_disable_related_content_bulk([user_sole, user_multi])

        addon_sole.reload()
        addon_multi.reload()
        # if sole dev should have been disabled, but the author retained
        assert addon_sole.status == amo.STATUS_DISABLED
        assert list(addon_sole.authors.all()) == [user_sole]
        # shouldn't have been disabled as it has another author
        assert addon_multi.status != amo.STATUS_DISABLED
        assert list(addon_multi.authors.all()) == [innocent_user]

        # the File objects have been disabled
        assert (
            not File.objects.filter(version__addon=addon_sole)
            .exclude(status=amo.STATUS_DISABLED)
            .exists()
        )
        # But not for the Add-on that wasn't disabled
        assert (
            File.objects.filter(version__addon=addon_multi)
            .exclude(status=amo.STATUS_DISABLED)
            .exists()
        )

        assert not user_sole._ratings_all.exists()  # Even replies.
        assert not user_sole.collections.exists()
        assert not user_multi._ratings_all.exists()  # Even replies.
        assert not user_multi.collections.exists()

        assert not self.storage.exists(user_sole.picture_path)
        assert not self.storage.exists(user_sole.picture_path_original)
        assert not self.storage.exists(user_multi.picture_path)
        assert not self.storage.exists(user_multi.picture_path_original)

        assert user_sole.deleted
        self.assertCloseToNow(user_sole.banned)
        self.assertCloseToNow(user_sole.modified)
        assert user_sole.email == 'sole@foo.baa'
        assert user_sole.auth_id
        assert user_sole.fxa_id == '13579'
        assert user_sole.last_login_ip == '127.0.0.1'
        assert user_multi.deleted
        self.assertCloseToNow(user_multi.banned)
        self.assertCloseToNow(user_multi.modified)
        assert user_multi.email == 'multi@foo.baa'
        assert user_multi.auth_id
        assert user_multi.fxa_id == '24680'
        assert user_multi.last_login_ip == '127.0.0.2'

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
        update_search_index.assert_called_with(sender=Addon, instance=addon)

        # The add-on should not have been touched, it has another dev.
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
        assert (
            new_rating.pk in review_list
        ), 'Original review must show up in ratings list.'
        assert (
            new_reply.pk not in review_list
        ), 'Developer reply must not show up in ratings list.'

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

    def test_is_public(self):
        user = UserProfile.objects.get(id=4043307)
        assert not user.addonuser_set.exists()
        assert not user.is_public

        addon = Addon.objects.get(pk=3615)
        addon_user = addon.addonuser_set.create(user=user)
        assert user.is_public

        # Only developer and owner roles make a profile public.
        addon_user.update(role=amo.AUTHOR_ROLE_DEV)
        assert user.is_public
        addon_user.update(role=amo.AUTHOR_ROLE_OWNER)
        assert user.is_public
        # But only if they're listed
        addon_user.update(role=amo.AUTHOR_ROLE_OWNER, listed=False)
        assert not user.is_public
        addon_user.update(listed=True)
        assert user.is_public
        addon_user.update(role=amo.AUTHOR_ROLE_DEV, listed=False)
        assert not user.is_public
        addon_user.update(listed=True)
        assert user.is_public

        # The add-on needs to be public.
        self.make_addon_unlisted(addon)  # Easy way to toggle status
        assert not user.reload().is_public
        self.make_addon_listed(addon)
        addon.update(status=amo.STATUS_APPROVED)
        assert user.reload().is_public

        addon.delete()
        assert not user.reload().is_public

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


class TestDeniedName(TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        assert DeniedName.blocked('IE6Fan')
        assert DeniedName.blocked('IE6fantastic')
        assert not DeniedName.blocked('IE6')
        assert not DeniedName.blocked('testo')


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

    def test_email_allowed(self):
        EmailUserRestriction.objects.create(email_pattern='foo@bar.com')
        request = RequestFactory().get('/')
        request.user = user_factory(email='bar@foo.com')
        assert EmailUserRestriction.allow_submission(request)
        assert EmailUserRestriction.allow_email(
            request.user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )

    def test_blocked_email(self):
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

    def test_changes_something_else(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(last_login=self.days_ago(0))
        assert self.index_addons_mock.delay.call_count == 0


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
