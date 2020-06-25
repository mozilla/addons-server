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
    try:
        raise RuntimeError('this is an exception from celery')
    except Exception as exception:
        log.exception('Capturing exception as a log', exc_info=exception)
        raise exception
