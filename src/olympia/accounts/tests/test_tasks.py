from datetime import datetime

from olympia.accounts.tasks import primary_email_change_event
from olympia.accounts.tests.test_utils import totimestamp
from olympia.amo.tests import TestCase, user_factory


class TestPrimaryEmailChangeEvent(TestCase):

    def test_success(self):
        user = user_factory(email='old-email@example.com',
                            fxa_id='ABCDEF012345689')
        primary_email_change_event(
            'new-email@example.com', 'ABCDEF012345689',
            totimestamp(datetime(2017, 10, 11)))
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == datetime(2017, 10, 11, 0, 0)

    def test_ignored_because_old_timestamp(self):
        user = user_factory(email='old-email@example.com',
                            fxa_id='ABCDEF012345689')
        yesterday = datetime(2017, 10, 1)
        today = datetime(2017, 10, 2)
        tomorrow = datetime(2017, 10, 3)

        primary_email_change_event(
            'today@example.com', 'ABCDEF012345689', totimestamp(today))
        assert user.reload().email == 'today@example.com'

        primary_email_change_event(
            'tomorrow@example.com', 'ABCDEF012345689', totimestamp(tomorrow))
        assert user.reload().email == 'tomorrow@example.com'

        primary_email_change_event(
            'yesterday@example.com', 'ABCDEF012345689', totimestamp(yesterday))
        assert user.reload().email != 'yesterday@example.com'
        assert user.reload().email == 'tomorrow@example.com'

    def test_ignored_if_user_not_found(self):
        """Check that this doesn't throw"""
        primary_email_change_event(
            'email@example.com', 'ABCDEF012345689',
            totimestamp(datetime(2017, 10, 11)))
