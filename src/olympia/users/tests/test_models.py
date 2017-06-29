# -*- coding: utf-8 -*-
import datetime

import django  # noqa
from django import forms
from django.db import models, migrations
from django.db.migrations.writer import MigrationWriter

import pytest
from waffle.models import Switch
from waffle.testutils import override_switch

import olympia  # noqa
from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, safe_exec
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.bandwagon.models import Collection, CollectionWatcher
from olympia.reviews.models import Review
from olympia.users.models import (
    DeniedName, UserEmailField, UserProfile,
    UserForeignKey)
from olympia.users.utils import find_users


class TestUserProfile(TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'base/user_4043307',
                'users/test_backends')

    def test_is_developer(self):
        user = UserProfile.objects.get(id=4043307)
        assert not user.addonuser_set.exists()
        assert not user.is_developer

        addon = Addon.objects.get(pk=3615)
        addon.addonuser_set.create(user=user)

        assert not user.is_developer  # it's a cached property...
        del user.is_developer  # ... let's reset it and try again.
        assert user.is_developer

        addon.delete()
        del user.is_developer
        assert not user.is_developer

    def test_delete(self):
        u = UserProfile.objects.get(id='4043307')
        assert u.email == 'jbalogh@mozilla.com'
        u.delete()
        x = UserProfile.objects.get(id='4043307')
        assert x.email is None

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
        assert user.has_anonymous_username()

    def test_has_anonymous_username_username_set(self):
        user = UserProfile(username='bob', display_name=None)
        assert not user.has_anonymous_username()

    def test_has_anonymous_username_display_name_set(self):
        user = UserProfile(display_name='Bob Bobbertson')
        user.anonymize_username()
        assert user.has_anonymous_username()

    def test_has_anonymous_username_both_names_set(self):
        user = UserProfile(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_username()

    def test_has_anonymous_display_name_no_names(self):
        user = UserProfile(display_name=None)
        user.anonymize_username()
        assert user.has_anonymous_display_name()

    def test_has_anonymous_display_name_username_set(self):
        user = UserProfile(username='bob', display_name=None)
        assert not user.has_anonymous_display_name()

    def test_has_anonymous_display_name_display_name_set(self):
        user = UserProfile(display_name='Bob Bobbertson')
        user.anonymize_username()
        assert not user.has_anonymous_display_name()

    def test_has_anonymous_display_name_both_names_set(self):
        user = UserProfile(username='bob', display_name='Bob Bobbertson')
        assert not user.has_anonymous_display_name()

    def test_add_admin_powers(self):
        user = UserProfile.objects.get(username='jbalogh')

        assert not user.is_staff
        assert not user.is_superuser
        GroupUser.objects.create(group=Group.objects.get(name='Admins'),
                                 user=user)
        assert user.is_staff
        assert user.is_superuser

    def test_dont_add_admin_powers(self):
        Group.objects.create(name='API', rules='API.Users:*')
        u = UserProfile.objects.get(username='jbalogh')

        GroupUser.objects.create(group=Group.objects.get(name='API'),
                                 user=u)
        assert not u.is_staff
        assert not u.is_superuser

    def test_remove_admin_powers(self):
        Group.objects.create(name='Admins', rules='*:*')
        u = UserProfile.objects.get(username='jbalogh')
        g = GroupUser.objects.create(
            group=Group.objects.filter(name='Admins')[0], user=u)
        g.delete()
        assert not u.is_staff
        assert not u.is_superuser

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile(id=1234, picture_type='image/png',
                        modified=datetime.date.today())
        u.picture_url.index('/userpics/0/1/1234.png?modified=')

        u = UserProfile(id=1234567890, picture_type='image/png',
                        modified=datetime.date.today())
        u.picture_url.index('/userpics/1234/1234567/1234567890.png?modified=')

        u = UserProfile(id=1234, picture_type=None)
        assert u.picture_url.endswith('/anon_user.png')

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=2519)
        version = addon.find_latest_public_listed_version()
        new_review = Review(version=version, user=u, rating=2, body='hello',
                            addon=addon)
        new_review.save()
        new_reply = Review(version=version, user=u, reply_to=new_review,
                           addon=addon, body='my reply')
        new_reply.save()

        review_list = [r.pk for r in u.reviews]

        assert len(review_list) == 1
        assert new_review.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')

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
        now = self.days_ago(0)
        recently = self.days_ago(1)
        older_date = self.days_ago(42)

        assert not UserProfile().has_read_developer_agreement()
        assert not UserProfile(
            read_dev_agreement=None).has_read_developer_agreement()
        assert UserProfile(
            read_dev_agreement=older_date).has_read_developer_agreement()
        with override_switch('post-review', active=True):
            Switch.objects.filter(name='post-review').update(modified=recently)

            # Still False.
            assert not UserProfile().has_read_developer_agreement()

            # User has read the agreement, before it was modified for
            # post-review: it should return False.
            assert not UserProfile(
                read_dev_agreement=older_date).has_read_developer_agreement()
            # User has read the agreement after it was modified for
            # post-review: it should return True.
            assert UserProfile(
                read_dev_agreement=now).has_read_developer_agreement()

        with override_switch('post-review', active=False):
            Switch.objects.filter(name='post-review').update(modified=recently)

            # Still False.
            assert not UserProfile().has_read_developer_agreement()

            # Both should be True, the date does not matter any more.
            assert UserProfile(
                read_dev_agreement=older_date).has_read_developer_agreement()
            assert UserProfile(
                read_dev_agreement=now).has_read_developer_agreement()


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
