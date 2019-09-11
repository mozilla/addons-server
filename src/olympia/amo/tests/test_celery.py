import time
import datetime

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.signals import request_finished, request_started
from django.test.testcases import TransactionTestCase

from post_request_task.task import _discard_tasks, _stop_queuing_tasks
from celery import states as celery_states

from olympia.amo.celery import task
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.amo.tests import CeleryWorkerTestCase


fake_task_func = mock.Mock()


def test_celery_routes_in_queues():
    queues_in_queues = set([q.name for q in settings.CELERY_TASK_QUEUES])

    # check the default queue is defined in CELERY_QUEUES
    assert settings.CELERY_TASK_DEFAULT_QUEUE in queues_in_queues

    # then remove it as it won't be in CELERY_ROUTES
    queues_in_queues.remove(settings.CELERY_TASK_DEFAULT_QUEUE)

    queues_in_routes = set(
        [c['queue'] for c in settings.CELERY_TASK_ROUTES.values()])
    assert queues_in_queues == queues_in_routes


@task(ignore_result=False)
def fake_task_with_result():
    fake_task_func()
    return 'foobar'


@task
def fake_task():
    fake_task_func()
    return 'foobar'


@task(track_started=True, ignore_result=False)
def sleeping_task(time_to_sleep):
    time.sleep(time_to_sleep)


class TestCeleryWorker(CeleryWorkerTestCase):
    def test_celery_worker_test_runs_through_worker(self):
        result = sleeping_task.delay(time_to_sleep=0.5)
        assert result.state == celery_states.PENDING

        # First the task will have the `STARTED` state
        self.assert_result_tasks_has_state([result], celery_states.STARTED)

        # and then eventually `SUCCESS`
        self.assert_result_tasks_has_state([result], celery_states.SUCCESS)

    def test_celery_default_ignore_result(self):
        result = fake_task.delay().get()
        assert result is None

    def test_celery_explicit_dont_ignore_result(self):
        result = fake_task_with_result.delay().get()
        assert result == 'foobar'

    def test_wait_for_tasks(self):
        result = fake_task_with_result.delay()
        assert self.wait_for_tasks(result.id)['retval'] == 'foobar'

    @mock.patch('olympia.amo.celery.cache')
    def test_start_task_timer(self, celery_cache):
        result = fake_task_with_result.delay()
        result.get()

        assert celery_cache.set.called
        assert (
            celery_cache.set.call_args[0][0] ==
            f'task_start_time.{result.id}')

    @mock.patch('olympia.amo.celery.cache')
    @mock.patch('olympia.amo.celery.statsd')
    def test_track_run_time(self, celery_statsd, celery_cache):
        minute_ago = datetime.datetime.now() - timedelta(minutes=1)
        task_start = utc_millesecs_from_epoch(minute_ago)
        celery_cache.get.return_value = task_start

        result = fake_task_with_result.delay()
        result.get()

        approx_run_time = utc_millesecs_from_epoch() - task_start
        assert (celery_statsd.timing.call_args[0][0] ==
                'tasks.olympia.amo.tests.test_celery.fake_task_with_result')
        actual_run_time = celery_statsd.timing.call_args[0][1]

        fuzz = 2000  # 2 seconds
        assert (actual_run_time >= (approx_run_time - fuzz) and
                actual_run_time <= (approx_run_time + fuzz))

        assert (
            celery_cache.get.call_args[0][0] ==
            f'task_start_time.{result.id}')
        assert (
            celery_cache.delete.call_args[0][0] ==
            f'task_start_time.{result.id}')

    @mock.patch('olympia.amo.celery.cache')
    @mock.patch('olympia.amo.celery.statsd')
    def test_handle_cache_miss_for_stats(self, celery_cache, celery_statsd):
        celery_cache.get.return_value = None  # cache miss
        fake_task.delay()
        assert not celery_statsd.timing.called


class TestTaskQueued(CeleryWorkerTestCase, TransactionTestCase):
    """Test that tasks are queued and only triggered when a request finishes.

    Tests our integration with django-post-request-task.
    """

    def setUp(self):
        super().setUp()
        fake_task_func.reset_mock()
        _discard_tasks()

    def tearDown(self):
        super().tearDown()
        fake_task_func.reset_mock()
        _discard_tasks()
        _stop_queuing_tasks()

    def test_not_queued_outside_request_response_cycle(self):
        self.wait_for_tasks(fake_task.delay())
        assert fake_task_func.call_count == 1

    def test_queued_inside_request_response_cycle(self):
        request_started.send(sender=self)
        result = fake_task.delay()
        self.wait_for_tasks(result, throw=False)
        assert fake_task_func.call_count == 0
        request_finished.send_robust(sender=self)
        self.wait_for_tasks(result, throw=False)
        assert fake_task_func.call_count == 1

    def test_no_dedupe_outside_request_response_cycle(self):
        r1 = fake_task.delay()
        r2 = fake_task.delay()
        self.wait_for_tasks((r1, r2))
        assert fake_task_func.call_count == 2

    def test_dedupe_inside_request_response_cycle(self):
        request_started.send(sender=self)
        r1 = fake_task.delay()
        r2 = fake_task.delay()
        self.wait_for_tasks((r1, r2), throw=False)
        assert fake_task_func.call_count == 0
        request_finished.send_robust(sender=self)
        self.wait_for_tasks((r1, r2), throw=False)
        assert fake_task_func.call_count == 1
