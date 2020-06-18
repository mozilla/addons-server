from datetime import datetime
from unittest import mock

from olympia import amo
from olympia.accounts.tasks import (
    delete_user_event, primary_email_change_event)
from olympia.accounts.tests.test_utils import totimestamp
from olympia.amo.tests import (
    addon_factory, collection_factory, TestCase, user_factory)
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating


class TestPrimaryEmailChangeEvent(TestCase):
    fxa_id = 'ABCDEF012345689'

    def test_success(self):
        user = user_factory(email='old-email@example.com',
                            fxa_id=self.fxa_id)
        primary_email_change_event(
            self.fxa_id,
            totimestamp(datetime(2017, 10, 11)),
            'new-email@example.com')
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == datetime(2017, 10, 11, 0, 0)

    def test_ignored_because_old_timestamp(self):
        user = user_factory(email='old-email@example.com',
                            fxa_id=self.fxa_id)
        yesterday = datetime(2017, 10, 1)
        today = datetime(2017, 10, 2)
        tomorrow = datetime(2017, 10, 3)

        primary_email_change_event(
            self.fxa_id,
            totimestamp(today),
            'today@example.com')
        assert user.reload().email == 'today@example.com'

        primary_email_change_event(
            self.fxa_id,
            totimestamp(tomorrow),
            'tomorrow@example.com')
        assert user.reload().email == 'tomorrow@example.com'

        primary_email_change_event(
            self.fxa_id,
            totimestamp(yesterday),
            'yesterday@example.com')
        assert user.reload().email != 'yesterday@example.com'
        assert user.reload().email == 'tomorrow@example.com'

    def test_ignored_if_user_not_found(self):
        """Check that this doesn't throw"""
        primary_email_change_event(
            self.fxa_id,
            totimestamp(datetime(2017, 10, 11)),
            'email@example.com')


class TestDeleteUserEvent(TestCase):
    fxa_id = 'ABCDEF012345689'

    def setUp(self):
        self.user = user_factory(fxa_id=self.fxa_id)

    def _fire_event(self):
        delete_user_event(
            self.fxa_id,
            totimestamp(datetime(2017, 10, 11)))
        self.user.reload()
        assert self.user.email is not None
        assert self.user.deleted
        assert self.user.fxa_id is not None

    @mock.patch('olympia.users.models.UserProfile.delete_picture')
    def test_success_basic(self, delete_picture_mock):
        collection = collection_factory(author=self.user)
        another_addon = addon_factory()
        Rating.objects.create(addon=another_addon, user=self.user, rating=5)
        assert list(another_addon.ratings.all().values('rating', 'user')) == [{
            'user': self.user.id, 'rating': 5}]
        self._fire_event()
        assert not Collection.objects.filter(id=collection.id).exists()
        assert not another_addon.ratings.all().exists()
        delete_picture_mock.assert_called()

    def test_success_addons(self):
        addon = addon_factory(users=[self.user])
        self._fire_event()
        addon.reload()
        assert addon.status == amo.STATUS_DELETED

    def test_success_addons_other_owners(self):
        other_owner = user_factory()
        addon = addon_factory(users=[self.user, other_owner])
        self._fire_event()
        addon.reload()
        assert addon.status != amo.STATUS_DELETED
        assert list(addon.authors.all()) == [other_owner]
