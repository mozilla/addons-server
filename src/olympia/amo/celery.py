"""Loads and instantiates Celery, registers our tasks, and performs any other
necessary Celery-related setup. Also provides Celery-related utility methods,
in particular exposing a shortcut to the @task decorator."""
from __future__ import absolute_import

import datetime

from django.conf import settings
from django.core.cache import cache

from celery import Celery, group
from celery.signals import task_failure, task_postrun, task_prerun
from django_statsd.clients import statsd
from kombu import serialization
from post_request_task.task import PostRequestTask
from raven import Client
from raven.contrib.celery import register_logger_signal, register_signal

import olympia.core.logger

from olympia.amo.utils import chunked, utc_millesecs_from_epoch


class AMOTask(PostRequestTask):
    """A custom celery Task base class that inherits from `PostRequestTask`
    to delay tasks and adds a special hack to still perform a serialization
    roundtrip in eager mode, to mimic what happens in production in tests.

    The serialization is applied both to apply_async() and apply() to work
    around the fact that celery groups have their own apply_async() method that
    directly calls apply() on each task in eager mode.

    Note that we should never somehow be using eager mode with actual workers,
    that would cause them to try to serialize data that has already been
    serialized...
    """
    abstract = True

    def _serialize_args_and_kwargs_for_eager_mode(
            self, args=None, kwargs=None, **options):
        producer = options.get('producer')
        with app.producer_or_acquire(producer) as eager_producer:
            serializer = options.get(
                'serializer', eager_producer.serializer
            )
            body = args, kwargs
            content_type, content_encoding, data = serialization.dumps(
                body, serializer
            )
            args, kwargs = serialization.loads(
                data, content_type, content_encoding
            )
        return args, kwargs

    def apply_async(self, args=None, kwargs=None, **options):
        if app.conf.task_always_eager:
            args, kwargs = self._serialize_args_and_kwargs_for_eager_mode(
                args=args, kwargs=kwargs, **options)

        return super(AMOTask, self).apply_async(
            args=args, kwargs=kwargs, **options)

    def apply(self, args=None, kwargs=None, **options):
        if app.conf.task_always_eager:
            args, kwargs = self._serialize_args_and_kwargs_for_eager_mode(
                args=args, kwargs=kwargs, **options)

        return super(AMOTask, self).apply(args=args, kwargs=kwargs, **options)


app = Celery('olympia', task_cls=AMOTask)
task = app.task

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Hook up Sentry in celery.
raven_client = Client(settings.SENTRY_DSN)

# register a custom filter to filter out duplicate logs
register_logger_signal(raven_client)

# hook into the Celery error handler
register_signal(raven_client)

# After upgrading raven we can specify loglevel=logging.INFO to override
# the default (which is ERROR).
register_logger_signal(raven_client)


@task_failure.connect
def process_failure_signal(exception, traceback, sender, task_id,
                           signal, args, kwargs, einfo, **kw):
    """Catch any task failure signals from within our worker processes and log
    them as exceptions, so they appear in Sentry and ordinary logging
    output."""

    exc_info = (type(exception), exception, traceback)
    log.error(
        u'Celery TASK exception: {0.__name__}: {1}'.format(*exc_info),
        exc_info=exc_info,
        extra={
            'data': {
                'task_id': task_id,
                'sender': sender,
                'args': args,
                'kwargs': kwargs
            }
        })


@task_prerun.connect
def start_task_timer(task_id, task, **kw):
    timer = TaskTimer()
    log.info('starting task timer; id={id}; name={name}; '
             'current_dt={current_dt}'
             .format(id=task_id, name=task.name,
                     current_dt=timer.current_datetime))

    # Cache start time for one hour. This will allow us to catch crazy long
    # tasks. Currently, stats indexing tasks run around 20-30 min.
    expiration = 60 * 60
    cache.set(timer.cache_key(task_id), timer.current_epoch_ms, expiration)


@task_postrun.connect
def track_task_run_time(task_id, task, **kw):
    timer = TaskTimer()
    start_time = cache.get(timer.cache_key(task_id))
    if start_time is None:
        log.info('could not track task run time; id={id}; name={name}; '
                 'current_dt={current_dt}'
                 .format(id=task_id, name=task.name,
                         current_dt=timer.current_datetime))
    else:
        run_time = timer.current_epoch_ms - start_time
        log.info('tracking task run time; id={id}; name={name}; '
                 'run_time={run_time}; current_dt={current_dt}'
                 .format(id=task_id, name=task.name,
                         current_dt=timer.current_datetime,
                         run_time=run_time))
        statsd.timing('tasks.{}'.format(task.name), run_time)
        cache.delete(timer.cache_key(task_id))


class TaskTimer(object):

    def __init__(self):
        self.current_datetime = datetime.datetime.now()
        self.current_epoch_ms = utc_millesecs_from_epoch(
            self.current_datetime)

    def cache_key(self, task_id):
        return 'task_start_time.{}'.format(task_id)


def create_subtasks(task, qs, chunk_size, countdown=None, task_args=None):
    """
    Splits a task depending on a queryset into a bunch of subtasks of the
    specified chunk_size, passing a chunked queryset and optional additional
    arguments to each."""
    if task_args is None:
        task_args = ()

    job = group([
        task.subtask(args=(chunk,) + task_args)
        for chunk in chunked(qs, chunk_size)
    ])

    if countdown is not None:
        job.apply_async(countdown=countdown)
    else:
        job.apply_async()
