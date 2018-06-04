# -*- coding: utf-8 -*-
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.accounts.serializers import (
    BaseUserSerializer, PublicUserProfileSerializer,
    UserNotificationSerializer, UserProfileSerializer)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, days_ago, user_factory
from olympia.users.models import UserNotification, UserProfile
from olympia.users.notifications import NOTIFICATIONS_BY_SHORT


class TestBaseUserSerializer(TestCase):
    serializer_class = BaseUserSerializer

    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()

    def serialize(self):
        # Manually reload the user first to clear any cached properties.
        self.user = UserProfile.objects.get(pk=self.user.pk)
        serializer = self.serializer_class(context={'request': self.request})
        return serializer.to_representation(self.user)

    def test_basic(self):
        result = self.serialize()
        assert result['id'] == self.user.pk
        assert result['name'] == self.user.name
        assert result['url'] is None

    def test_url_for_yourself(self):
        # should include account profile url
        self.request.user = self.user
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_url_for_developers(self):
        # should include account profile url
        addon_factory(users=[self.user])
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_url_for_admins(self):
        # should include account profile url
        admin = user_factory()
        self.grant_permission(admin, 'Users:Edit')
        self.request.user = admin
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_username(self):
        serialized = self.serialize()
        assert serialized['username'] == self.user.username


class TestPublicUserProfileSerializer(TestCase):
    serializer = PublicUserProfileSerializer
    user_kwargs = {
        'username': 'amo',
        'biography': 'stuff', 'homepage': 'http://mozilla.org/',
        'location': 'everywhere', 'occupation': 'job'}

    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory(**self.user_kwargs)

    def serialize(self):
        return (self.serializer(context={'request': self.request})
                .to_representation(self.user))

    def test_picture(self):
        serial = self.serialize()
        assert serial['picture_url'] is None
        assert serial['picture_type'] is None
        assert 'picture_upload' not in serial  # its a write only field.

        self.user.update(picture_type='image/jpeg')
        serial = self.serialize()
        assert serial['picture_url'] == absolutify(self.user.picture_url)
        assert '%s.png' % self.user.id in serial['picture_url']

    def test_basic(self):
        data = self.serialize()
        for prop, val in self.user_kwargs.items():
            assert data[prop] == unicode(val), prop
        return data

    def test_addons(self):
        self.user.update(averagerating=3.6)
        assert self.serialize()['num_addons_listed'] == 0

        addon_factory(users=[self.user])
        addon_factory(users=[self.user])
        addon_factory(status=amo.STATUS_NULL, users=[self.user])
        data = self.serialize()
        assert data['num_addons_listed'] == 2  # only public addons.
        assert data['average_addon_rating'] == 3.6

    def test_url_for_non_developers(self):
        result = self.serialize()
        assert result['url'] is None

    def test_url_for_developers(self):
        # should include the account profile url for a developer
        addon_factory(users=[self.user])
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_url_for_admins(self):
        # should include account profile url for admins
        admin = user_factory()
        self.grant_permission(admin, 'Users:Edit')
        self.request.user = admin
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_anonymous_username_display_name(self):
        self.user = user_factory(
            username='anonymous-bb4f3cbd422e504080e32f2d9bbfcee0')
        data = self.serialize()
        assert self.user.has_anonymous_username is True
        assert data['has_anonymous_username'] is True
        assert self.user.has_anonymous_display_name is True
        assert data['has_anonymous_display_name'] is True

        self.user.update(display_name=u'Bób dé bob')
        data = self.serialize()
        assert data['has_anonymous_username'] is True
        assert data['has_anonymous_display_name'] is False

        self.user.update(username='bob')
        data = self.serialize()
        assert data['has_anonymous_username'] is False
        assert data['has_anonymous_display_name'] is False


class PermissionsTestMixin(object):
    def test_permissions(self):
        assert self.serializer(self.user).data['permissions'] == []

        # Single permission
        group = Group.objects.create(name='a', rules='Addons:Review')
        GroupUser.objects.create(group=group, user=self.user)
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Review']

        # Multiple permissions
        group.update(rules='Addons:Review,Personas:Review,Addons:Edit')
        del self.user.groups_list
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit', 'Addons:Review', 'Personas:Review']

        # Change order to test sort
        group.update(rules='Personas:Review,Addons:Review,Addons:Edit')
        del self.user.groups_list
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit', 'Addons:Review', 'Personas:Review']

        # Add a second group membership to test duplicates
        group2 = Group.objects.create(name='b', rules='Foo:Bar,Addons:Edit')
        GroupUser.objects.create(group=group2, user=self.user)
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit', 'Addons:Review', 'Foo:Bar', 'Personas:Review']


class TestUserProfileSerializer(TestPublicUserProfileSerializer,
                                PermissionsTestMixin):
    serializer = UserProfileSerializer

    def setUp(self):
        self.now = days_ago(0)
        self.user_kwargs.update({
            'email': u'a@m.o',
            'display_name': u'This is my náme',
            'last_login_ip': '123.45.67.89',
        })
        super(TestUserProfileSerializer, self).setUp()

    def test_basic(self):
        # Have to update these separately as dates as tricky.  As are bools.
        self.user.update(last_login=self.now, read_dev_agreement=self.now)
        data = super(TestUserProfileSerializer, self).test_basic()
        assert data['last_login'] == (
            self.now.replace(microsecond=0).isoformat() + 'Z')
        assert data['read_dev_agreement'] == data['last_login']


class TestUserNotificationSerializer(TestCase):

    def setUp(self):
        self.user = user_factory()

    def test_basic(self):
        notification = NOTIFICATIONS_BY_SHORT['upgrade_fail']
        user_notification = UserNotification.objects.create(
            user=self.user, notification_id=notification.id, enabled=True)
        data = UserNotificationSerializer(user_notification).data
        assert data['name'] == user_notification.notification.short
        assert data['enabled'] == user_notification.enabled
        assert data['mandatory'] == user_notification.notification.mandatory
