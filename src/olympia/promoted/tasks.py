from django.db.models import Q

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.constants.promoted import NOTABLE, NOT_PROMOTED
from olympia.zadmin.models import get_config

from .models import PromotedAddon

log = olympia.core.logger.getLogger('z.promoted.tasks')

ADU_LIMIT_CONFIG_KEY = 'notable-adu-threshold'


@task
@use_primary_db
def add_high_adu_extensions_to_notable():
    """Add add-ons with high ADU to Notable promoted group."""

    adu_limit = get_config(ADU_LIMIT_CONFIG_KEY)
    if not adu_limit or not adu_limit.isdecimal():
        log.error('[%s] config key not set or not an integer', ADU_LIMIT_CONFIG_KEY)
        return
    adu_limit = int(adu_limit)

    addons_ids_and_slugs = (
        Addon.objects.public()
        .filter(
            Q(promotedaddon=None) | Q(promotedaddon__group_id=NOT_PROMOTED.id),
            average_daily_users__gte=adu_limit,
            type=amo.ADDON_EXTENSION,
        )
        .values_list('id', 'slug', 'average_daily_users')
    )
    count = len(addons_ids_and_slugs)
    log.info('Starting adding %s addons to %s', count, NOTABLE.name)
    for addon_id, addon_slug, adu in addons_ids_and_slugs:
        promo, created = PromotedAddon.objects.get_or_create(
            addon_id=addon_id, defaults={'group_id': NOTABLE.id}
        )
        if not created:
            if promo.group != NOT_PROMOTED:
                # Shouldn't happen because filter only includes NOT_PROMOTED.
                log.warning(
                    'With addon id[%s], attempt to overwrite %s with %s. Skipping',
                    addon_id,
                    promo.group.name,
                    NOTABLE.name,
                )
                continue
            promo.group_id = NOTABLE.id
            promo.save()
        log.info(
            '%s addon id[%s], slug[%s], with ADU[%s] to %s.',
            ('Adding' if created else 'Updating'),
            addon_id,
            addon_slug,
            adu,
            NOTABLE.name,
        )
    log.info('Done adding %s addons to %s', count, NOTABLE.name)
