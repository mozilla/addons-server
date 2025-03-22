from django.conf import settings
from django.db.models import Value
from django.db.models.functions import Replace

import nh3

import olympia.core.logger
from olympia.addons.models import Addon
from olympia.addons.tasks import index_addons
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


@task
@use_primary_db
def strip_html_from_summaries(pks, **kwargs):
    """
    Run translations of Add-on summaries through bleach to strip them
    of HTML.

    Used to clean up old summaries from when we accepted URLs in summaries and
    turned them into HTML.
    """
    # Note: can't just use PureTranslation.clean(), because we want to strip
    # the HTML and not just escape it here - We used to create that HTML
    # automatically, so it's out responsability to remove it, escaping it not
    # enough.
    translations = Translation.objects.filter(pk__in=pks)
    for translation in translations:
        translation.localized_string = nh3.clean(
            str(translation.localized_string), tags=set(), attributes={}
        )
        translation.localized_string_clean = translation.localized_string
        translation.save()
    addon_ids = list(
        Addon.unfiltered.filter(
            # `<translation>.id` is different from `<translation.pk>`, so we need
            # that list comprehension, can't use `translations` directly.
            summary_id__in=[translation.id for translation in translations]
        ).values_list('pk', flat=True)
    )
    index_addons.delay(addon_ids)
