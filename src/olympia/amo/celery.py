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
from raven import Client
from raven.contrib.celery import register_signal, register_logger_signal

import olympia.core.logger
from olympia.amo.utils import chunked, utc_millesecs_from_epoch


log = olympia.core.logger.getLogger('z.task')


app = Celery('olympia')
task = app.task

app.config_from_object('django.conf:settings')
app.autodiscover_tasks(settings.INSTALLED_APPS)

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
