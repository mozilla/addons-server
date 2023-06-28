from olympia.amo.decorators import use_primary_db
from olympia.amo.celery import task
from olympia.translations.models import PurifiedTranslation, LinkifiedTranslation
import olympia.core.logger
import settings

log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def clean_outgoing_urls(ids, meta_type, dry_run=True, **kw):
    """Cleans up translation objects that need to be re-processed following a change in REDIRECT_URL"""
    stats = {
        'cleaned': 0,
        'skipped': 0,
        'failed': 0,
    }

    # The last known outgoing url from ticket #203 (https://github.com/thundernest/addons-server/issues/203)
    known_old_outgoing_url = 'outgoing.prod.mozaws.net'
    outgoing_url = settings.REDIRECT_URL

    translations = []

    if meta_type == 'purified':
        translations = PurifiedTranslation.objects.filter(id__in=ids)
    elif meta_type == 'linkified':
        translations = LinkifiedTranslation.objects.filter(id__in=ids)
    else:
        log.warning("[translations.tasks.clean_outgoing_urls] Unknown translation meta type: {meta_type}. Skipping...").format(meta_type=meta_type)
        return

    for translation in translations:
        # Ignore already cleaned urls
        if outgoing_url and outgoing_url in translation.localized_string_clean:
            stats['skipped'] += 1
            continue

        # Clean the old outgoing url from the translation
        translation.clean()

        if outgoing_url and outgoing_url in translation.localized_string_clean:
            stats['cleaned'] += 1
        elif not outgoing_url and known_old_outgoing_url not in translation.localized_string_clean:  # No real way to check for this
            stats['cleaned'] += 1
        else:
            stats['failed'] += 1
            continue

        if not dry_run:
            translation.save()

    log.info("[translations.tasks.clean_outgoing_urls] Chunk finished with a total of {ids} translations processed. {cleaned} translations cleaned, {skipped} translations skipped, and {failed} translations failed.".format(ids=len(ids), cleaned=stats['cleaned'], skipped=stats['skipped'], failed=stats['failed']))

    if dry_run:
        log.info("[translations.tasks.clean_outgoing_urls] Dry run is enabled, no processed translations were saved.")

