import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.translations.models import NoURLsTranslation


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def reclean_collection_descriptions(ids, **kw):
    log.info('Recleaning translation of ids %d-%d [%d].', ids[0], ids[-1], len(ids))
    translations = NoURLsTranslation.objects.filter(pk__in=ids)
    for translation in translations:
        translation.save()
