import olympia.core.logger

from olympia.amo.celery import task


log = olympia.core.logger.getLogger('z.task')


@task
def celery_error(*, capture_and_log=False, **kw):
    """
    This task raises an exception from celery to test error logging and
    Sentry hookup.
    """
    log.info('About to raise an exception from celery')
    try:
        raise RuntimeError('This is an exception from celery')
    except Exception as exception:
        if capture_and_log:
            log.exception(
                'Capturing celery exception as a log', exc_info=exception)
        else:
            raise exception
