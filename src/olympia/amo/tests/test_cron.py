import datetime
import unittest
from datetime import timedelta

import mock

from olympia.amo.celery import task
from olympia.amo.utils import utc_millesecs_from_epoch


@task
def fake_task(**kw):
    pass


class TestTaskTiming(unittest.TestCase):

    def setUp(self):
        patch = mock.patch('olympia.amo.celery.cache', autospec=True)
        self.cache = patch.start()
        self.addCleanup(patch.stop)

        patch = mock.patch('olympia.amo.celery.statsd', autospec=True)
        self.statsd = patch.start()
        self.addCleanup(patch.stop)

    def test_cache_start_time(self):
        fake_task.delay()
        assert self.cache.set.call_args[0][0].startswith('task_start_time')

    def test_track_run_time(self):
        minute_ago = datetime.datetime.now() - timedelta(minutes=1)
        task_start = utc_millesecs_from_epoch(minute_ago)
        self.cache.get.return_value = task_start

        fake_task.delay()

        approx_run_time = utc_millesecs_from_epoch() - task_start
        assert (self.statsd.timing.call_args[0][0] ==
                'tasks.olympia.amo.tests.test_cron.fake_task')
        actual_run_time = self.statsd.timing.call_args[0][1]

        fuzz = 2000  # 2 seconds
        assert (actual_run_time >= (approx_run_time - fuzz) and
                actual_run_time <= (approx_run_time + fuzz))

        assert self.cache.get.call_args[0][0].startswith('task_start_time')
        assert self.cache.delete.call_args[0][0].startswith('task_start_time')

    def test_handle_cache_miss_for_stats(self):
        self.cache.get.return_value = None  # cache miss
        fake_task.delay()
        assert not self.statsd.timing.called
