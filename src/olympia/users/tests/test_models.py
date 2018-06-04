# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta

import django  # noqa

from django import forms
from django.db import migrations, models
from django.db.migrations.writer import MigrationWriter
from django.contrib.auth import get_user
from django.core.files.storage import default_storage as storage
from django.test.client import RequestFactory

import mock
import pytest

import olympia  # noqa

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, addon_factory, safe_exec, user_factory
from olympia.bandwagon.models import Collection, CollectionWatcher
from olympia.ratings.models import Rating
from olympia.users.models import (
    DeniedName, generate_auth_id, UserEmailField, UserForeignKey, UserProfile)
from olympia.users.utils import find_users
from olympia.zadmin.models import set_config


class TestUserProfile(TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'users/test_backends')

    def test_is_developer(self):
        user = UserProfile.objects.get(id=4043307)
        assert not user.addonuser_set.exists()
        assert not user.is_developer

        addon = Addon.objects.get(pk=3615)
        addon.addonuser_set.create(user=user)

        assert not user.is_developer  # it's a cached property...
        del user.cached_developer_status  # ... let's reset it and try again.
        assert user.is_developer

        addon.delete()
        del user.cached_developer_status
        assert not user.is_developer

    def test_is_addon_developer(self):
        user = UserProfile.objects.get(pk=4043307)
        assert not user.addonuser_set.exists()
        assert not user.is_addon_developer
        addon = Addon.objects.get(pk=3615)
        addon.addonuser_set.create(user=user)

        del user.cached_developer_status
        assert user.is_addon_developer

        addon.delete()
        del user.cached_developer_status
        assert not user.is_addon_developer

    def test_delete(self):
        user = UserProfile.objects.get(pk=4043307)

        # Create a photo so that we can test deletion.
        with storage.open(user.picture_path, 'wb') as fobj:
            fobj.write('test data\n')

        with storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write('original test data\n')

        assert storage.exists(user.picture_path_original)
        assert storage.exists(user.picture_path)

        assert not user.deleted
        assert user.email == 'jbalogh@mozilla.com'
        assert user.auth_id
        assert user.fxa_id == '0824087ad88043e2a52bd41f51bbbe79'
        assert user.username == 'jbalogh'
        assert user.display_name
        assert user.homepage
        assert user.picture_type
        assert user.last_login_attempt
        assert user.last_login_attempt_ip
        assert user.last_login_ip
        assert not user.has_anonymous_username

        old_auth_id = user.auth_id
        user.delete()
        user = UserProfile.objects.get(pk=4043307)
        assert user.email is None
        assert user.auth_id
        assert user.auth_id != old_auth_id
        assert user.fxa_id is None
        assert user.display_name is None
        assert user.homepage == ''
        assert user.picture_type is None
        assert user.last_login_attempt is None
        assert user.last_login_attempt_ip == ''
        assert user.last_login_ip == ''
        assert user.has_anonymous_username
        assert not storage.exists(user.picture_path)
        assert not storage.exists(user.picture_path_original)

    @mock.patch.object(UserProfile, 'delete_or_disable_related_content')
    def test_ban_and_disable_related_content(
            self, delete_or_disable_related_content_mock):
        user = UserProfile.objects.get(pk=4043307)
        user.ban_and_disable_related_content()
        user.reload()
        assert user.deleted
        assert user.email == 'jbalogh@mozilla.com'
        assert user.auth_id
        assert user.fxa_id == '0824087ad88043e2a52bd41f51bbbe79'

        assert delete_or_disable_related_content_mock.call_count == 1
        assert (
            delete_or_disable_related_content_mock.call_args[1] ==
            {'delete': False})

    def test_delete_or_disable_related_content(self):
        addon = Addon.objects.latest('pk')
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with storage.open(user.picture_path, 'wb') as fobj:
            fobj.write('test data\n')

        with storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write('original test data\n')

        assert user.addons.count() == 1
        rating = Rating.objects.create(
            user=user, addon=addon, version=addon.current_version)
        Rating.objects.create(
            user=user, addon=addon, version=addon.current_version,
            reply_to=rating)
        Collection.objects.create(author=user)

        # Now that everything is set up, disable/delete related content.
        user.delete_or_disable_related_content()

        assert user.addons.exists()
        addon.reload()
        assert addon.status == amo.STATUS_DISABLED

        assert not user._ratings_all.exists()  # Even replies.
        assert not user.collections.exists()

        assert not storage.exists(user.picture_path)
        assert not storage.exists(user.picture_path_original)

    def delete_or_disable_related_content_exclude_addons_with_other_devs(self):
        addon = Addon.objects.latest('pk')
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')
        AddonUser.objects.create(addon=addon, user=user_factory())

        # Create a photo so that we can test deletion.
        with storage.open(user.picture_path, 'wb') as fobj:
            fobj.write('test data\n')

        with storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write('original test data\n')

        assert user.addons.count() == 1
        rating = Rating.objects.create(
            user=user, addon=addon, version=addon.current_version)
        Rating.objects.create(
            user=user, addon=addon, version=addon.current_version,
            reply_to=rating)
        Collection.objects.create(author=user)

        # Now that everything is set up, disable/delete related content.
        user.delete_or_disable_related_content()

        # The add-on should not have been touched, it has another dev.
        assert user.addons.exists()
        addon.reload()
        assert addon.status == amo.STATUS_PUBLIC

        assert not user._ratings_all.exists()  # Even replies.
        assert not user.collections.exists()

        assert not storage.exists(user.picture_path)
        assert not storage.exists(user.picture_path_original)

    def delete_or_disable_related_content_actually_delete(self):
        addon = Addon.objects.latest('pk')
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with storage.open(user.picture_path, 'wb') as fobj:
            fobj.write('test data\n')

        with storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write('original test data\n')

        assert user.addons.count() == 1
        rating = Rating.objects.create(
            user=user, addon=addon, version=addon.current_version)
        Rating.objects.create(
            user=user, addon=addon, version=addon.current_version,
            reply_to=rating)
        Collection.objects.create(author=user)

        # Now that everything is set up, delete related content.
        user.delete_or_disable_related_content(delete=True)

        assert not user.addons.exists()

        assert not user._ratings_all.exists()  # Even replies.
        assert not user.collections.exists()

        assert not storage.exists(user.picture_path)
        assert not storage.exists(user.picture_path_original)

    def test_delete_picture(self):
        user = UserProfile.objects.get(pk=55021)
        user.update(picture_type='image/png')

        # Create a photo so that we can test deletion.
        with storage.open(user.picture_path, 'wb') as fobj:
            fobj.write('test data\n')

        with storage.open(user.picture_path_original, 'wb') as fobj:
            fobj.write('original test data\n')

        user.delete_picture()

        user.reload()
        assert user.picture_type is None
        assert not storage.exists(user.picture_path)
        assert not storage.exists(user.picture_path_original)

    def test_groups_list(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        group1 = Group.objects.create(name='un')
        group2 = Group.objects.create(name='deux')
        GroupUser.objects.create(user=user, group=group1)
        GroupUser.objects.create(user=user, group=group2)
        assert user.groups_list == list(user.groups.all())
        assert len(user.groups_list) == 2

        # Remove the user from the groups, groups_list should not have changed
        # since it's a cached property.
        GroupUser.objects.filter(group=group1).delete()
        assert len(user.groups_list) == 2

    def test_welcome_name(self):
        u1 = UserProfile(username='sc')
        u2 = UserProfile(username='sc', display_name="Sarah Connor")
        u3 = UserProfile()
        assert u1.welcome_name == 'sc'
        assert u2.welcome_name == 'Sarah Connor'
        assert u3.welcome_name == ''

    def test_welcome_name_anonymous(self):
        user = UserProfile(
            username='anonymous-bb4f3cbd422e504080e32f2d9bbfcee0')
        assert user.welcome_name == 'Anonymous user bb4f3c'

    def test_welcome_name_anonymous_with_display(self):
        user = UserProfile(display_name='John Connor')
        user.anonymize_username()
        assert user.welcome_name == 'John Connor'

    def test_has_anonymous_username_no_names(self):
        user = UserProfile(display_name=None)
        user.anonymize_username()
        assert user.has_anonymous_username

    def test_has_anonymous_username_username_set(self):
        user = UserProfile(username='bob', display_name=None)
        assert not user.has_anonymous_username

    def test_has_anonymous_username_display_name_set(self):
        user = UserProfile(display_name='Bob Bobbertson')
        user.anonymize_username()
        assert user.has_anonymous_username

    def test_has_anonymous_username_both_names_set(self):
        user = UserProfile(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_username

    def test_has_anonymous_display_name_no_names(self):
        user = UserProfile(display_name=None)
        user.anonymize_username()
        assert user.has_anonymous_display_name

    def test_has_anonymous_display_name_username_set(self):
        user = UserProfile(username='bob', display_name=None)
        assert not user.has_anonymous_display_name

    def test_has_anonymous_display_name_display_name_set(self):
        user = UserProfile(display_name='Bob Bobbertson')
        user.anonymize_username()
        assert not user.has_anonymous_display_name

    def test_has_anonymous_display_name_both_names_set(self):
        user = UserProfile(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_display_name

    def test_superuser(self):
        user = UserProfile.objects.get(username='jbalogh')
        assert not user.is_staff
        assert not user.is_superuser

        # Give the user '*:*'.
        group = Group.objects.filter(rules='*:*').get()
        GroupUser.objects.create(group=group, user=user)
        assert user.is_staff
        assert user.is_superuser

    def test_staff_only(self):
        group = Group.objects.create(
            name='Admins of Something', rules='Admin:Something')
        user = UserProfile.objects.get(username='jbalogh')
        assert not user.is_staff
        assert not user.is_superuser

        GroupUser.objects.create(group=group, user=user)
        # User now has access to an Admin permission, so is_staff is True.
        assert user.is_staff
        assert not user.is_superuser

    def test_remove_admin_powers(self):
        group = Group.objects.create(name='Admins', rules='*:*')
        user = UserProfile.objects.get(username='jbalogh')
        relation = GroupUser.objects.create(group=group, user=user)
        relation.delete()
        assert not user.is_staff
        assert not user.is_superuser

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile(id=1234, picture_type='image/png',
                        modified=date.today())
        u.picture_url.index('/userpics/0/1/1234.png?modified=')

        u = UserProfile(id=1234567890, picture_type='image/png',
                        modified=date.today())
        u.picture_url.index('/userpics/1234/1234567/1234567890.png?modified=')

        u = UserProfile(id=1234, picture_type=None)
        assert u.picture_url.endswith('/anon_user.png')

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original ratings.
        """
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=2519)
        version = addon.find_latest_public_listed_version()
        new_rating = Rating(version=version, user=user, rating=2, body='hello',
                            addon=addon)
        new_rating.save()
        new_reply = Rating(version=version, user=user, reply_to=new_rating,
                           addon=addon, body='my reply')
        new_reply.save()

        review_list = [rating.pk for rating in user.ratings]

        assert len(review_list) == 1
        assert new_rating.pk in review_list, (
            'Original review must show up in ratings list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in ratings list.')

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
        assert sorted(a.name for a in addons) == [addon1.name, addon2.name]

    def test_mobile_collection(self):
        u = UserProfile.objects.get(id='4043307')
        assert not Collection.objects.filter(author=u)

        c = u.mobile_collection()
        assert c.type == amo.COLLECTION_MOBILE
        assert c.slug == 'mobile'

    def test_favorites_collection(self):
        u = UserProfile.objects.get(id='4043307')
        assert not Collection.objects.filter(author=u)

        c = u.favorites_collection()
        assert c.type == amo.COLLECTION_FAVORITES
        assert c.slug == 'favorites'

    def test_get_url_path(self):
        assert UserProfile(username='yolo').get_url_path() == (
            '/en-US/firefox/user/yolo/')
        assert UserProfile(username='yolo', id=1).get_url_path() == (
            '/en-US/firefox/user/yolo/')
        assert UserProfile(id=1).get_url_path() == (
            '/en-US/firefox/user/1/')
        assert UserProfile(username='<yolo>', id=1).get_url_path() == (
            '/en-US/firefox/user/1/')

    def test_mobile_addons(self):
        user = UserProfile.objects.get(id='4043307')
        addon1 = Addon.objects.create(name='test-1', type=amo.ADDON_EXTENSION)
        addon2 = Addon.objects.create(name='test-2', type=amo.ADDON_EXTENSION)
        mobile_collection = user.mobile_collection()
        mobile_collection.add_addon(addon1)
        other_collection = Collection.objects.create(name='other')
        other_collection.add_addon(addon2)
        assert user.mobile_addons.count() == 1
        assert user.mobile_addons[0] == addon1.pk

    def test_favorite_addons(self):
        user = UserProfile.objects.get(id='4043307')
        addon1 = Addon.objects.create(name='test-1', type=amo.ADDON_EXTENSION)
        addon2 = Addon.objects.create(name='test-2', type=amo.ADDON_EXTENSION)
        favorites_collection = user.favorites_collection()
        favorites_collection.add_addon(addon1)
        other_collection = Collection.objects.create(name='other')
        other_collection.add_addon(addon2)
        assert user.favorite_addons.count() == 1
        assert user.favorite_addons[0] == addon1.pk

    def test_watching(self):
        user = UserProfile.objects.get(id='4043307')
        watched_collection1 = Collection.objects.create(name='watched-1')
        watched_collection2 = Collection.objects.create(name='watched-2')
        Collection.objects.create(name='other')
        CollectionWatcher.objects.create(user=user,
                                         collection=watched_collection1)
        CollectionWatcher.objects.create(user=user,
                                         collection=watched_collection2)
        assert len(user.watching) == 2
        assert tuple(user.watching) == (watched_collection1.pk,
                                        watched_collection2.pk)

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
        set_config('last_dev_agreement_change_date', '2018-01-01 00:00')
        after_change = (
            datetime(2018, 1, 1) + timedelta(days=1))
        before_change = (
            datetime(2018, 1, 1) - timedelta(days=42))

        assert not UserProfile().has_read_developer_agreement()
        assert not UserProfile(
            read_dev_agreement=None).has_read_developer_agreement()
        assert not UserProfile(
            read_dev_agreement=before_change).has_read_developer_agreement()

        # User has read the agreement after it was modified for
        # post-review: it should return True.
        assert UserProfile(
            read_dev_agreement=after_change).has_read_developer_agreement()

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
        addon.update(status=amo.STATUS_PUBLIC)
        assert user.reload().is_public

        addon.delete()
        assert not user.reload().is_public


class TestDeniedName(TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        assert DeniedName.blocked('IE6Fan')
        assert DeniedName.blocked('IE6fantastic')
        assert not DeniedName.blocked('IE6')
        assert not DeniedName.blocked('testo')


class TestUserEmailField(TestCase):
    fixtures = ['base/user_2519']

    def test_success(self):
        user = UserProfile.objects.get(pk=2519)
        assert UserEmailField().clean(user.email) == user

    def test_failure(self):
        with pytest.raises(forms.ValidationError):
            UserEmailField().clean('xxx')

    def test_empty_email(self):
        UserProfile.objects.create(email='')
        with pytest.raises(forms.ValidationError) as exc_info:
            UserEmailField().clean('')

        assert exc_info.value.messages[0] == 'This field is required.'


class TestOnChangeName(TestCase):
    def setUp(self):
        super(TestOnChangeName, self).setUp()

        # We're in a regular TestCase class so index_addons should have been
        # mocked.
        from olympia.addons.tasks import index_addons
        self.index_addons_mock = index_addons

    def test_changes_display_name_not_a_listed_author(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=False)
        self.index_addons_mock.reset_mock()
        user.update(display_name=u'bâr')
        assert self.index_addons_mock.delay.call_count == 0

    def test_changes_display_name(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(display_name=u'bâr')
        assert self.index_addons_mock.delay.call_count == 1
        assert self.index_addons_mock.delay.call_args[0] == ([addon.pk],)

    def test_changes_username(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(username=u'föo')
        assert self.index_addons_mock.delay.call_count == 1
        assert self.index_addons_mock.delay.call_args[0] == ([addon.pk],)

    def test_changes_something_else(self):
        user = user_factory()
        addon = addon_factory()
        AddonUser.objects.create(user=user, addon=addon, listed=True)
        self.index_addons_mock.reset_mock()

        user.update(last_login=self.days_ago(0))
        assert self.index_addons_mock.delay.call_count == 0


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
        user_1 = UserProfile.objects.create(username='user_1',
                                            email='luke@jedi.com')
        user_1.update(email='dark@sith.com')
        user_2 = UserProfile.objects.create(username='user_2',
                                            email='luke@jedi.com')
        assert [user_1, user_2] == list(find_users('luke@jedi.com'))


class TestUserManager(TestCase):
    fixtures = ('users/test_backends', )

    def test_create_user(self):
        user = UserProfile.objects.create_user("test", "test@test.com", 'xxx')
        assert user.pk is not None

    def test_create_superuser(self):
        user = UserProfile.objects.create_superuser(
            "test",
            "test@test.com",
        )
        assert user.pk is not None
        Group.objects.get(name="Admins") in user.groups.all()
        assert user.is_staff
        assert user.is_superuser


def test_user_foreign_key_supports_migration():
    """Tests serializing UserForeignKey in a simple migration.

    Since `UserForeignKey` is a ForeignKey migrations pass `to=` explicitly
    and we have to pop it in our __init__.
    """
    fields = {
        'charfield': UserForeignKey(),
    }

    migration = type(str('Migration'), (migrations.Migration,), {
        'operations': [
            migrations.CreateModel(
                name='MyModel', fields=tuple(fields.items()),
                bases=(models.Model,)
            ),
        ],
    })
    writer = MigrationWriter(migration)
    output = writer.as_string()

    # Just make sure it runs and that things look alright.
    result = safe_exec(output, globals_=globals())

    assert 'Migration' in result


def test_user_foreign_key_field_deconstruct():
    field = UserForeignKey()
    name, path, args, kwargs = field.deconstruct()
    new_field_instance = UserForeignKey()

    assert kwargs['to'] == new_field_instance.to


@pytest.mark.django_db
def test_get_session_auth_hash_is_used_for_session_auth():
    user = user_factory()
    client = amo.tests.TestClient()
    assert not client.session.items()
    assert client.login(email=user.email)
    assert client.session.items()

    request = RequestFactory().get('/')
    request.session = client.session
    assert get_user(request) == user

    user.update(auth_id=generate_auth_id())
    assert get_user(request) != user
