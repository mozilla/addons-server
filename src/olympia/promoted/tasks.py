from django.db.models import Q

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.constants.promoted import (
    PROMOTED_GROUP_CHOICES,
)
from olympia.reviewers.models import UsageTier
from olympia.versions.utils import get_staggered_review_due_date_generator

from .models import PromotedAddon


log = olympia.core.logger.getLogger('z.promoted.tasks')

NOTABLE_TIER_SLUG = 'notable'


@task
@use_primary_db
def add_high_adu_extensions_to_notable():
    """Add add-ons with high ADU to Notable promoted group."""
    try:
        lower_adu_threshold = UsageTier.objects.get(
            slug=NOTABLE_TIER_SLUG
        ).lower_adu_threshold
    except UsageTier.DoesNotExist:
        lower_adu_threshold = None
    if not lower_adu_threshold:
        return

    due_date_generator = get_staggered_review_due_date_generator()
    addons_ids_and_slugs = Addon.unfiltered.filter(
        ~Q(status=amo.STATUS_DISABLED),
        Q(promotedaddon=None)
        | Q(promotedaddon__group_id=PROMOTED_GROUP_CHOICES.NOT_PROMOTED),
        average_daily_users__gte=lower_adu_threshold,
        type=amo.ADDON_EXTENSION,
    ).values_list('id', 'slug', 'average_daily_users')
    count = len(addons_ids_and_slugs)
    log.info(
        'Starting adding %s addons to %s',
        count,
        PROMOTED_GROUP_CHOICES.NOTABLE.api_value,
    )
    for addon_id, addon_slug, adu in addons_ids_and_slugs:
        due_date = next(due_date_generator)
        try:
            # We can't use update_or_create because we need to pass _due_date to save
            promo = PromotedAddon.objects.get(addon_id=addon_id)
            if promo.group_id != PROMOTED_GROUP_CHOICES.NOT_PROMOTED:
                # Shouldn't happen because filter only includes NOT_PROMOTED.
                log.warning(
                    'With addon id[%s], attempt to overwrite %s with %s. Skipping',
                    addon_id,
                    promo.group.name,
                    PROMOTED_GROUP_CHOICES.NOTABLE.api_value,
                )
                continue
            promo.group_id = PROMOTED_GROUP_CHOICES.NOTABLE
            created = False
        except PromotedAddon.DoesNotExist:
            promo = PromotedAddon(
                addon_id=addon_id, group_id=PROMOTED_GROUP_CHOICES.NOTABLE
            )
            created = True
        promo.save(_due_date=due_date)

        log.info(
            '%s addon id[%s], slug[%s], with ADU[%s] to %s.',
            ('Adding' if created else 'Updating'),
            addon_id,
            addon_slug,
            adu,
            PROMOTED_GROUP_CHOICES.NOTABLE.api_value,
        )
    log.info(
        'Done adding %s addons to %s', count, PROMOTED_GROUP_CHOICES.NOTABLE.api_value
    )
