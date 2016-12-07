# -*- coding: utf-8 -*-
from olympia import amo
from olympia.amo.tests import (
    addon_factory, TestCase, days_ago, user_factory)
from olympia.accounts.serializers import (
    PublicUserProfileSerializer, UserNotificationSerializer,
    UserProfileSerializer)
from olympia.users.models import UserNotification
from olympia.users.notifications import NOTIFICATIONS_BY_SHORT


class TestPublicUserProfileSerializer(TestCase):
    serializer = PublicUserProfileSerializer
    user_kwargs = {
        'username': 'amo',
        'biography': 'stuff', 'homepage': 'http://mozilla.org/',
        'location': 'everywhere', 'occupation': 'job'}

    def setUp(self):
        self.user = user_factory(**self.user_kwargs)

    def serialize(self):
        return self.serializer(self.user).data

    def test_picture(self):
        serial = self.serialize()
        assert ('anon_user.png' in serial['picture_url'])
        assert serial['picture_type'] == ''
        assert 'picture_upload' not in serial  # its a write only field.

        self.user.update(picture_type='image/jpeg')
        serial = self.serialize()
        assert serial['picture_url'] == self.user.picture_url
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
        assert data['average_addon_rating'] == '3.6'


class TestUserProfileSerializer(TestPublicUserProfileSerializer):
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
        self.user.update(last_login=self.now, read_dev_agreement=self.now,
                         is_verified=True)
        data = super(TestUserProfileSerializer, self).test_basic()
        assert data['is_verified'] is True
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
