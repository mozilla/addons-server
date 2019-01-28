import olympia.core.logger

from olympia.amo.celery import task


log = olympia.core.logger.getLogger('z.task')


@task
def celery_error(**kw):
    """
    This task raises an exception from celery to test error logging and
    Sentry hookup.
    """
    log.info('about to raise an exception from celery')
    raise RuntimeError('this is an exception from celery')
