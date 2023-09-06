import json
from datetime import timedelta

from freezegun import freeze_time

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.users.models import UserProfile


class LogTest(TestCase):
    def setUp(self):
        super().setUp()
        u = UserProfile.objects.create(username='foo')
        core.set_user(u)

    def test_details(self):
        """
        If we get details, verify they are stored as JSON, and we get out what
        we put in.
        """
        addon = addon_factory(name='kümar is awesome')
        magic = {'title': 'nô', 'body': 'wày!'}
        al = ActivityLog.create(amo.LOG.DELETE_RATING, 1, addon, details=magic)

        assert al.details == magic
        assert al._details == json.dumps(magic)

    @freeze_time(amo.MZA_LAUNCH_DATETIME - timedelta(minutes=1), as_arg=True)
    def test_user_auto_deleted_says_fxa_before_mza_date_mza_after(frozen_time, self):
        user = user_factory()
        al = ActivityLog.create(amo.LOG.USER_AUTO_DELETED, user)
        assert 'from Firefox Accounts event' in str(al)

        frozen_time.move_to(amo.MZA_LAUNCH_DATETIME)
        assert 'from Mozilla accounts event' in str(al)
