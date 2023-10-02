import datetime
import importlib
import time
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.signals import request_finished, request_started
from django.test.testcases import TransactionTestCase

from celery import group
from post_request_task.task import _discard_tasks, _stop_queuing_tasks

from olympia.amo.celery import app, create_chunked_tasks_signatures, task
from olympia.amo.tests import TestCase
from olympia.amo.utils import utc_millesecs_from_epoch


fake_task_func = mock.Mock()


def test_celery_routes_in_queues():
    queues_in_queues = {q.name for q in settings.CELERY_TASK_QUEUES}

    # check the default queue is defined in CELERY_QUEUES
    assert settings.CELERY_TASK_DEFAULT_QUEUE in queues_in_queues

    queues_in_routes = {c['queue'] for c in settings.CELERY_TASK_ROUTES.values()}
    assert queues_in_queues == queues_in_routes


def test_celery_routes_only_contain_valid_tasks():
    # Import CELERY_IMPORTS like celery would to find additional tasks that
    # are not automatically imported at startup otherwise.
    for module_name in settings.CELERY_IMPORTS:
        importlib.import_module(module_name)

    # Force a re-discovery of the tasks - when running the tests the
    # autodiscovery might happen too soon.
    app.autodiscover_tasks(force=True)

    # Make sure all tasks in CELERY_TASK_ROUTES are known.
    known_tasks = app.tasks.keys()
    for task_name in settings.CELERY_TASK_ROUTES.keys():
        assert task_name in known_tasks

    # Make sure all known tasks have an explicit route set.
    for task_name in known_tasks:
        assert task_name in settings.CELERY_TASK_ROUTES.keys()


def test_create_chunked_tasks_signatures():
    items = list(range(0, 6))
    batch = create_chunked_tasks_signatures(fake_task, items, 2)
    assert isinstance(batch, group)
    assert len(batch) == 3
    assert batch.tasks[0] == fake_task.si([items[0], items[1]])
    assert batch.tasks[1] == fake_task.si([items[2], items[3]])
    assert batch.tasks[2] == fake_task.si([items[4], items[5]])

    batch = create_chunked_tasks_signatures(
        fake_task,
        items,
        3,
        task_args=('foo', 'bar'),
        task_kwargs={'some': 'kwarg'},
    )
    assert isinstance(batch, group)
    assert len(batch) == 2
    assert batch.tasks[0] == fake_task.si(
        [items[0], items[1], items[2]], 'foo', 'bar', some='kwarg'
    )
    assert batch.tasks[1] == fake_task.si(
        [items[3], items[4], items[5]], 'foo', 'bar', some='kwarg'
    )


@task(ignore_result=False)
def fake_task_with_result():
    fake_task_func()
    return 'foobar'


@task
def fake_task(*args, **kwargs):
    fake_task_func()
    return 'foobar'


@task(track_started=True, ignore_result=False)
def sleeping_task(time_to_sleep):
    time.sleep(time_to_sleep)


class TestCeleryWorker(TestCase):
    @mock.patch('olympia.amo.celery.cache')
    def test_start_task_timer(self, celery_cache):
        result = fake_task_with_result.delay()
        result.get()

        assert celery_cache.set.called
        assert celery_cache.set.call_args[0][0] == f'task_start_time.{result.id}'

    @mock.patch('olympia.amo.celery.cache')
    @mock.patch('olympia.amo.celery.statsd')
    def test_track_run_time(self, celery_statsd, celery_cache):
        minute_ago = datetime.datetime.now() - timedelta(minutes=1)
        task_start = utc_millesecs_from_epoch(minute_ago)
        celery_cache.get.return_value = task_start

        result = fake_task_with_result.delay()
        result.get()

        approx_run_time = utc_millesecs_from_epoch() - task_start
        assert (
            celery_statsd.timing.call_args[0][0]
            == 'tasks.olympia.amo.tests.test_celery.fake_task_with_result'
        )
        actual_run_time = celery_statsd.timing.call_args[0][1]

        fuzz = 2000  # 2 seconds
        assert actual_run_time >= (approx_run_time - fuzz) and actual_run_time <= (
            approx_run_time + fuzz
        )

        assert celery_cache.get.call_args[0][0] == f'task_start_time.{result.id}'
        assert celery_cache.delete.call_args[0][0] == f'task_start_time.{result.id}'

    @mock.patch('olympia.amo.celery.cache')
    @mock.patch('olympia.amo.celery.statsd')
    def test_handle_cache_miss_for_stats(self, celery_cache, celery_statsd):
        celery_cache.get.return_value = None  # cache miss
        fake_task.delay()
        assert not celery_statsd.timing.called


class TestTaskQueued(TransactionTestCase):
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
