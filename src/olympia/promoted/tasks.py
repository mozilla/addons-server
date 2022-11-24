from django.db.models import Q

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.constants.promoted import NOTABLE, NOT_PROMOTED
from olympia.zadmin.models import get_config

from .models import PromotedAddon

log = olympia.core.logger.getLogger('z.promoted.tasks')

ADU_LIMIT_CONFIG_KEY = 'notable-adu-threshold'


@task
def add_high_adu_extensions_to_notable(items):
    """Add add-ons with high ADU to Notable promoted group.
    See `update_addon_average_daily_users` for details of items."""

    adu_limit = get_config(ADU_LIMIT_CONFIG_KEY)
    if not adu_limit or not adu_limit.isdecimal():
        log.error('[%s] config key not set or not an integer', ADU_LIMIT_CONFIG_KEY)
        return
    adu_limit = int(adu_limit)
    items_above_limit = {guid: count for guid, count in items if count >= adu_limit}

    addons_ids_and_slugs = (
        Addon.objects.public()
        .filter(
            Q(promotedaddon=None) | Q(promotedaddon__group_id=NOT_PROMOTED.id),
            guid__in=items_above_limit,
            type=amo.ADDON_EXTENSION,
        )
        .values_list('guid', 'id', 'slug')
    )
    count = len(addons_ids_and_slugs)
    log.info('Starting adding %s addons to %s', count, NOTABLE.name)
    for addon_guid, addon_id, addon_slug in addons_ids_and_slugs:
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
            items_above_limit.get(addon_guid, 0),
            NOTABLE.name,
        )
    log.info('Done adding %s addons to %s', count, NOTABLE.name)
