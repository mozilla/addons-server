import logging
import functools

import celery.decorators
import celery.task


log = logging.getLogger('z.celery')


class Task(celery.task.Task):

    @classmethod
    def apply_async(self, args=None, kwargs=None, **options):
        try:
            return super(Task, self).apply_async(args, kwargs, **options)
        except Exception, e:
            log.error('CELERY FAIL: %s' % e)


def task(*args, **kw):
    # Force usage of our Task subclass.
    kw['base'] = Task
    wrapper = celery.decorators.task(**kw)
    if args:
        return wrapper(*args)
    else:
        return wrapper
