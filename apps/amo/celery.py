"""Loads and instantiates Celery, registers our tasks, and performs any other
necessary Celery-related setup. Also provides Celery-related utility methods,
in particular exposing a shortcut to the @task decorator."""
from __future__ import absolute_import

import datetime

import commonware.log
from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun
from django.conf import settings
from django.core.cache import cache
from django_statsd.clients import statsd

from amo.utils import utc_millesecs_from_epoch


log = commonware.log.getLogger('z.task')


app = Celery('olympia')
task = app.task

app.config_from_object('django.conf:settings')
app.autodiscover_tasks(settings.INSTALLED_APPS)

# See olympia.py::init_celery() for more configuration.


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
