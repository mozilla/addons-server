import datetime

from datetime import timedelta

from django.core.signals import request_finished, request_started
from django.test.testcases import TransactionTestCase

import mock

from post_request_task.task import _discard_tasks, _stop_queuing_tasks

from olympia.amo.celery import task
from olympia.amo.tests import TestCase
from olympia.amo.utils import utc_millesecs_from_epoch


fake_task_func = mock.Mock()


@task
def fake_task(**kw):
    fake_task_func()


class TestTaskTiming(TestCase):

    def setUp(self):
        patch = mock.patch('olympia.amo.celery.cache')
        self.cache = patch.start()
        self.addCleanup(patch.stop)

        patch = mock.patch('olympia.amo.celery.statsd')
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
                'tasks.olympia.amo.tests.test_celery.fake_task')
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


class TestTaskQueued(TransactionTestCase):
    """Test that tasks are queued and only triggered when a request finishes.

    Tests our integration with django-post-request-task.
    """

    def setUp(self):
        super(TestTaskQueued, self).setUp()
        fake_task_func.reset_mock()
        _discard_tasks()

    def tearDown(self):
        fake_task_func.reset_mock()
        _discard_tasks()
        _stop_queuing_tasks()

    def test_not_queued_outside_request_response_cycle(self):
        fake_task.delay()
        assert fake_task_func.call_count == 1

    def test_queued_inside_request_response_cycle(self):
        request_started.send(sender=self)
        fake_task.delay()
        assert fake_task_func.call_count == 0
        request_finished.send_robust(sender=self)
        assert fake_task_func.call_count == 1

    def test_no_dedupe_outside_request_response_cycle(self):
        fake_task.delay()
        fake_task.delay()
        assert fake_task_func.call_count == 2

    def test_dedupe_inside_request_response_cycle(self):
        request_started.send(sender=self)
        fake_task.delay()
        fake_task.delay()
        assert fake_task_func.call_count == 0
        request_finished.send_robust(sender=self)
        assert fake_task_func.call_count == 1
