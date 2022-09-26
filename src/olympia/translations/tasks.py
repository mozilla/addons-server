from django.conf import settings
from django.db.models import Value
from django.db.models.functions import Replace

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.translations.models import Translation


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def update_outgoing_url(pks, *, old_outgoing_url, **kw):
    """Update localized_string/localized_string_clean to replace the old
    outgoing URL with the new one."""
    log.info(
        'Updating outgoing URLs in translations pks %d-%d [%d].',
        pks[0],
        pks[-1],
        len(pks),
    )
    # Note: we use <queryset>.update() and do the replace in SQL to avoid going
    # over each instance and calling .save(): not just because it's faster, but
    # also because that would automatically trigger clean(), but we don't know
    # what the right Translation class is, so doing so would mess with the HTML
    # handling: regular Translation should not allow it, PurifiedTranslation
    # should allow a specific set of tags and attributes and
    # LinkifiedTranslation should only allow links...
    Translation.objects.filter(pk__in=pks).update(
        localized_string=Replace(
            'localized_string', Value(old_outgoing_url), Value(settings.REDIRECT_URL)
        ),
        localized_string_clean=Replace(
            'localized_string_clean',
            Value(old_outgoing_url),
            Value(settings.REDIRECT_URL),
        ),
    )
