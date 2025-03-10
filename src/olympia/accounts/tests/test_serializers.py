from django.test.utils import override_settings

from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, days_ago, user_factory
from olympia.amo.utils import urlparams
from olympia.users.models import UserNotification, UserProfile
from olympia.users.notifications import NOTIFICATIONS_BY_SHORT
from olympia.zadmin.models import Config, set_config

from ..serializers import (
    BaseUserSerializer,
    FullUserProfileSerializer,
    MinimalUserProfileSerializer,
    SelfUserProfileSerializer,
    UserNotificationSerializer,
)


class BaseTestUserMixin:
    def serialize(self):
        # Manually reload the user first to clear any cached properties.
        self.user = UserProfile.objects.get(pk=self.user.pk)
        serializer = self.serializer_class(self.user, context={'request': self.request})
        return serializer.to_representation(self.user)

    def test_basic(self):
        result = self.serialize()
        assert result['id'] == self.user.pk
        assert result['name'] == self.user.name
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_username(self):
        serialized = self.serialize()
        assert serialized['username'] == self.user.username


class TestBaseUserSerializer(TestCase, BaseTestUserMixin):
    serializer_class = BaseUserSerializer

    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()


class TestFullUserProfileSerializer(TestCase):
    serializer = FullUserProfileSerializer
    user_kwargs = {
        'username': 'amo',
        'biography': 'stuff',
        'homepage': 'http://mozilla.org/',
        'location': 'everywhere',
        'occupation': 'job',
    }

    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory(**self.user_kwargs)

    def serialize(self):
        return self.serializer(
            self.user, context={'request': self.request}
        ).to_representation(self.user)

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
            assert data[prop] == str(val), prop
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

    def test_url(self):
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_anonymous_username_display_name(self):
        self.user = user_factory(username='anonymous-bb4f3cbd422e504080e32f2d9bbfcee0')
        data = self.serialize()
        assert self.user.has_anonymous_username is True
        assert data['has_anonymous_username'] is True
        assert self.user.has_anonymous_display_name is True
        assert data['has_anonymous_display_name'] is True

        self.user.update(display_name='Bób dé bob')
        data = self.serialize()
        assert data['has_anonymous_username'] is True
        assert data['has_anonymous_display_name'] is False

        self.user.update(username='bob')
        data = self.serialize()
        assert data['has_anonymous_username'] is False
        assert data['has_anonymous_display_name'] is False


class TestMinimalUserProfileSerializer(TestFullUserProfileSerializer):
    serializer = MinimalUserProfileSerializer
    gates = {None: ('mimimal-profile-has-all-fields-shim',)}

    def test_picture(self):
        self.user.update(picture_type='image/jpeg')
        data = self.serialize()
        assert 'picture_url' not in data
        assert 'picture_type' not in data

        with override_settings(DRF_API_GATES=self.gates):
            data = self.serialize()
            assert data['picture_url'] is None
            assert data['picture_type'] is None

    def test_basic(self):
        mimimal_data = {
            'id': self.user.id,
            'username': self.user.username,
            'name': self.user.name,
            'url': absolutify(self.user.get_url_path()),
        }
        data = self.serialize()
        assert data == mimimal_data

        with override_settings(DRF_API_GATES=self.gates):
            data = self.serialize()
            for field, value in mimimal_data.items():
                assert data[field] == value
            for field in MinimalUserProfileSerializer.nullable_fields:
                assert data[field] is None

    def test_anonymous_username_display_name(self):
        data = self.serialize()
        assert 'has_anonymous_username' not in data
        assert 'has_anonymous_display_name' not in data

        with override_settings(DRF_API_GATES=self.gates):
            super().test_anonymous_username_display_name()


class PermissionsTestMixin:
    def test_permissions(self):
        assert self.serializer(self.user).data['permissions'] == []

        # Single permission
        group = Group.objects.create(name='a', rules='Addons:Review')
        GroupUser.objects.create(group=group, user=self.user)
        assert self.serializer(self.user).data['permissions'] == ['Addons:Review']

        # Multiple permissions
        group.update(rules='Addons:Review,Addons:Edit')
        del self.user.groups_list
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit',
            'Addons:Review',
        ]

        # Change order to test sort
        group.update(rules='Addons:Edit,Addons:Review')
        del self.user.groups_list
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit',
            'Addons:Review',
        ]

        # Add a second group membership to test duplicates
        group2 = Group.objects.create(name='b', rules='Foo:Bar,Addons:Edit')
        GroupUser.objects.create(group=group2, user=self.user)
        assert self.serializer(self.user).data['permissions'] == [
            'Addons:Edit',
            'Addons:Review',
            'Foo:Bar',
        ]


class TestSelfUserProfileSerializer(
    TestFullUserProfileSerializer, PermissionsTestMixin
):
    serializer = SelfUserProfileSerializer

    def setUp(self):
        self.now = days_ago(0)
        self.user_email = 'a@m.o'
        self.user_kwargs.update(
            {
                'email': self.user_email,
                'display_name': 'This is my náme',
                'last_login_ip': '123.45.67.89',
            }
        )
        super().setUp()

    def test_basic(self):
        # Have to update these separately as dates as tricky.  As are bools.
        self.user.update(last_login=self.now, read_dev_agreement=self.now)
        data = super().test_basic()
        assert data['last_login'] == (self.now.replace(microsecond=0).isoformat() + 'Z')
        assert data['read_dev_agreement'] == data['last_login']

    def test_expose_fxa_edit_email_url(self):
        fxa_host = 'http://example.com'
        user_fxa_id = 'ufxa-id-123'
        self.user.update(fxa_id=user_fxa_id)

        with override_settings(FXA_CONTENT_HOST=fxa_host):
            expected_url = urlparams(
                f'{fxa_host}/settings',
                uid=user_fxa_id,
                email=self.user_email,
                entrypoint='addons',
            )

            data = super().test_basic()
            assert data['fxa_edit_email_url'] == expected_url

        # And to make sure it's not present in v3
        gates = {None: ('del-accounts-fxa-edit-email-url',)}
        with override_settings(DRF_API_GATES=gates):
            data = super().test_basic()
            assert 'fxa_edit_email_url' not in data

    def test_site_status(self):
        data = super().test_basic()
        assert data['site_status'] == {
            'read_only': False,
            'notice': None,
        }

        set_config('site_notice', 'THIS is NOT Á TEST!')
        data = super().test_basic()
        assert data['site_status'] == {
            'read_only': False,
            'notice': 'THIS is NOT Á TEST!',
        }

        with override_settings(READ_ONLY=True):
            data = super().test_basic()
        assert data['site_status'] == {
            'read_only': True,
            'notice': 'THIS is NOT Á TEST!',
        }

        Config.objects.get(key='site_notice').delete()
        with override_settings(READ_ONLY=True):
            data = super().test_basic()
        assert data['site_status'] == {
            'read_only': True,
            'notice': None,
        }


class TestUserNotificationSerializer(TestCase):
    def setUp(self):
        self.user = user_factory()

    def test_basic(self):
        notification = NOTIFICATIONS_BY_SHORT['upgrade_fail']
        user_notification = UserNotification.objects.create(
            user=self.user, notification_id=notification.id, enabled=True
        )
        data = UserNotificationSerializer(user_notification).data
        assert data['name'] == user_notification.notification.short
        assert data['enabled'] == user_notification.enabled
        assert data['mandatory'] == user_notification.notification.mandatory
