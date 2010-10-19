from nose.tools import eq_
from mock import Mock
import test_utils

import amo
from addons.models import Addon
from devhub.models import ActivityLog
from users.models import UserProfile


class TestActivityLog(test_utils.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        self.request = Mock()
        u = UserProfile(username='Joe CamelCase')
        u.save()
        self.request.amo_user = u

    def test_basic(self):
        request = self.request
        a = Addon.objects.get()
        ActivityLog.log(request, amo.LOG['CREATE_ADDON'], a)
        entries = ActivityLog.objects.for_addon(a)
        eq_(len(entries), 1)
        eq_(entries[0].arguments[0], a)
        eq_(unicode(entries[0]),
            'Joe CamelCase created addon Delicious Bookmarks')

    def test_json_failboat(self):
        request = self.request
        a = Addon.objects.get()
        ActivityLog.log(request, amo.LOG['CREATE_ADDON'], a)
        entry = ActivityLog.objects.get()
        entry._arguments = 'failboat?'
        entry.save()
        eq_(entry.arguments, None)

    def test_no_arguments(self):
        request = self.request
        ActivityLog.log(request, amo.LOG['CUSTOM_HTML'])
        entry = ActivityLog.objects.get()
        eq_(entry.arguments, [])

    def test_output(self):
        request = self.request
        ActivityLog.log(request, amo.LOG['CUSTOM_TEXT'], 'hi there')
        entry = ActivityLog.objects.get()
        eq_(unicode(entry), 'hi there')

    def test_user_log(self):
        request = self.request
        ActivityLog.log(request, amo.LOG['CUSTOM_TEXT'], 'hi there')
        entries = ActivityLog.objects.for_user(request.amo_user)
        eq_(len(entries), 1)

    def test_user_log_as_argument(self):
        """
        Tests that a user that has something done to them gets into the user
        log.
        """
        request = self.request
        u = UserProfile(username='Marlboro Manatee')
        u.save()
        ActivityLog.log(request, amo.LOG['ADD_USER_WITH_ROLE'],
                (u, 'developer', Addon.objects.get()))
        entries = ActivityLog.objects.for_user(request.amo_user)
        eq_(len(entries), 1)
        entries = ActivityLog.objects.for_user(u)
        eq_(len(entries), 1)

