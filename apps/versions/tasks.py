import logging

from celeryutils import task

from amo.decorators import write


log = logging.getLogger('z.task')


@task
@write
def update_supported_locales_single(id, latest=False, **kw):
    """
    Update supported_locales for an individual app. Set latest=True to use the
    latest current version instead of the most recent public version.
    """
    from mkt.webapps.models import Webapp

    try:
        app = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        log.info(u'[Webapp:%s] Did not find webapp to update supported '
                 u'locales.' % id)
        return

    try:
        if app.update_supported_locales(latest=latest):
            log.info(u'[Webapp:%s] Updated supported locales.' % app.id)
    except Exception:
        log.info(u'[Webapp%s] Updating supported locales failed.' % app.id,
                 exc_info=True)
