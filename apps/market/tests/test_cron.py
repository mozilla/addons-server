import time
from datetime import datetime, timedelta

import mock
from nose.tools import eq_

import amo
import amo.tests
from devhub.models import ActivityLog
from market.cron import mkt_gc
from users.models import UserProfile


class TestGarbage(amo.tests.TestCase):

    def setUp(self):
        self.user = UserProfile.objects.create(
            email='gc_test@example.com', name='gc_test')
        amo.log(amo.LOG.CUSTOM_TEXT, 'testing', user=self.user,
                created=datetime(2001, 1, 1))

    @mock.patch('os.stat')
    @mock.patch('os.listdir')
    @mock.patch('os.remove')
    def test_garbage_collection(self, rm_mock, ls_mock, stat_mock):
        eq_(ActivityLog.objects.all().count(), 1)
        mkt_gc()
        eq_(ActivityLog.objects.all().count(), 0)

    @mock.patch('os.stat')
    @mock.patch('os.listdir')
    @mock.patch('os.remove')
    def test_dump_delete(self, rm_mock, ls_mock, stat_mock):
        ls_mock.return_value = ['lol']
        stat_mock.return_value = StatMock(days_ago=1000)

        mkt_gc()
        assert rm_mock.call_args_list[0][0][0].endswith('lol')

    @mock.patch('os.stat')
    @mock.patch('os.listdir')
    @mock.patch('os.remove')
    def test_new_no_delete(self, rm_mock, ls_mock, stat_mock):
        ls_mock.return_value = ['lol']
        stat_mock.return_value = StatMock(days_ago=1)

        mkt_gc()
        assert not rm_mock.called


class StatMock(object):
    def __init__(self, days_ago):
        self.st_mtime = time.mktime(
            (datetime.now() - timedelta(days_ago)).timetuple())
        self.st_size = 100
