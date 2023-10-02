import time
from datetime import datetime
from unittest import mock

from waffle.testutils import override_switch

from olympia import amo
from olympia.accounts.tasks import (
    clear_sessions_event,
    delete_user_event,
    primary_email_change_event,
)
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating


def totimestamp(datetime_obj):
    return time.mktime(datetime_obj.timetuple())


class TestPrimaryEmailChangeEvent(TestCase):
    fxa_id = 'ABCDEF012345689'

    def test_success(self):
        user = user_factory(email='old-email@example.com', fxa_id=self.fxa_id)
        primary_email_change_event(
            self.fxa_id, totimestamp(datetime(2017, 10, 11)), 'new-email@example.com'
        )
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == datetime(2017, 10, 11, 0, 0)

    def test_ignored_because_old_timestamp(self):
        user = user_factory(email='old-email@example.com', fxa_id=self.fxa_id)
        yesterday = datetime(2017, 10, 1)
        today = datetime(2017, 10, 2)
        tomorrow = datetime(2017, 10, 3)

        primary_email_change_event(self.fxa_id, totimestamp(today), 'today@example.com')
        assert user.reload().email == 'today@example.com'

        primary_email_change_event(
            self.fxa_id, totimestamp(tomorrow), 'tomorrow@example.com'
        )
        assert user.reload().email == 'tomorrow@example.com'

        primary_email_change_event(
            self.fxa_id, totimestamp(yesterday), 'yesterday@example.com'
        )
        assert user.reload().email != 'yesterday@example.com'
        assert user.reload().email == 'tomorrow@example.com'

    def test_ignored_if_user_not_found(self):
        """Check that this doesn't throw"""
        primary_email_change_event(
            self.fxa_id, totimestamp(datetime(2017, 10, 11)), 'email@example.com'
        )


class TestDeleteUserEvent(TestCase):
    fxa_id = 'ABCDEF012345689'

    def setUp(self):
        self.user = user_factory(fxa_id=self.fxa_id)

    def _fire_event(self):
        delete_user_event(self.fxa_id, totimestamp(datetime(2017, 10, 11)))
        self.user.reload()
        assert self.user.email is not None
        assert self.user.deleted
        assert self.user.fxa_id is not None

    @mock.patch('olympia.users.models.UserProfile.delete_picture')
    @override_switch('fxa-account-delete', active=True)
    def test_success_basic(self, delete_picture_mock):
        collection = collection_factory(author=self.user)
        another_addon = addon_factory()
        Rating.objects.create(addon=another_addon, user=self.user, rating=5)
        assert list(another_addon.ratings.all().values('rating', 'user')) == [
            {'user': self.user.id, 'rating': 5}
        ]
        self._fire_event()
        assert not Collection.objects.filter(id=collection.id).exists()
        assert not another_addon.ratings.all().exists()
        delete_picture_mock.assert_called()
        alog = ActivityLog.objects.get(
            user=self.user, action=amo.LOG.USER_AUTO_DELETED.id
        )
        assert alog.arguments == [self.user]

    @override_switch('fxa-account-delete', active=True)
    def test_success_addons(self):
        addon = addon_factory(users=[self.user])
        self._fire_event()
        addon.reload()
        assert addon.status == amo.STATUS_DELETED

    @override_switch('fxa-account-delete', active=True)
    def test_success_addons_other_owners(self):
        other_owner = user_factory()
        addon = addon_factory(users=[self.user, other_owner])
        self._fire_event()
        addon.reload()
        assert addon.status != amo.STATUS_DELETED
        assert list(addon.authors.all()) == [other_owner]

    @override_switch('fxa-account-delete', active=False)
    def test_waffle_off(self):
        delete_user_event(self.fxa_id, totimestamp(datetime(2017, 10, 11)))
        self.user.reload()
        assert not self.user.deleted


class TestClearSessionsEvent(TestCase):
    fxa_id = 'ABCDEF012345689'

    def test_success(self):
        user = user_factory(auth_id=123456, fxa_id=self.fxa_id)
        assert user.auth_id is not None
        clear_sessions_event(
            self.fxa_id, totimestamp(datetime(2017, 10, 11)), 'passwordChanged'
        )
        assert user.reload().auth_id is None

    def test_ignored_because_old_timestamp(self):
        yesterday = datetime(2017, 10, 1)
        today = datetime(2017, 10, 2)
        tomorrow = datetime(2017, 10, 3)
        user = user_factory(auth_id=123456, fxa_id=self.fxa_id, last_login=today)

        clear_sessions_event(self.fxa_id, totimestamp(yesterday), 'passwordChanged')
        assert user.reload().auth_id is not None

        clear_sessions_event(self.fxa_id, totimestamp(tomorrow), 'passwordChanged')
        assert user.reload().auth_id is None

    def test_ignored_if_user_not_found(self):
        """Check that this doesn't throw"""
        clear_sessions_event(
            self.fxa_id, totimestamp(datetime(2017, 10, 11)), 'passwordChanged'
        )
