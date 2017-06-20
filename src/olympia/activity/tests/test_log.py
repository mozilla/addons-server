import json

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.users.models import UserProfile


class LogTest(TestCase):
    def setUp(self):
        super(LogTest, self).setUp()
        u = UserProfile.objects.create(username='foo')
        core.set_user(u)

    def test_details(self):
        """
        If we get details, verify they are stored as JSON, and we get out what
        we put in.
        """
        a = Addon.objects.create(name='kumar is awesome',
                                 type=amo.ADDON_EXTENSION)
        magic = dict(title='no', body='way!')
        al = ActivityLog.create(amo.LOG.DELETE_REVIEW, 1, a, details=magic)

        assert al.details == magic
        assert al._details == json.dumps(magic)
