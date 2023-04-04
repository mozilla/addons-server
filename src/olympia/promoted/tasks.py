from datetime import datetime, timedelta

from django.db.models import Q

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.constants.promoted import NOTABLE, NOT_PROMOTED
from olympia.versions.utils import get_review_due_date
from olympia.zadmin.models import get_config

from .models import PromotedAddon

log = olympia.core.logger.getLogger('z.promoted.tasks')

NOTABLE_ADU_LIMIT_CONFIG_KEY = 'notable-adu-threshold'
NOTABLE_REVIEW_TARGET_PER_DAY_CONFIG_KEY = 'notable-review-target-per-day'


@task
@use_primary_db
def add_high_adu_extensions_to_notable():
    """Add add-ons with high ADU to Notable promoted group."""

    def config(key):
        value = get_config(key)
        if not value or not value.isdecimal():
            log.error('[%s] config key not set or not an integer', key)
            return
        return int(value)

    adu_limit = config(NOTABLE_ADU_LIMIT_CONFIG_KEY)
    target_per_day = config(NOTABLE_REVIEW_TARGET_PER_DAY_CONFIG_KEY)
    if not adu_limit or not target_per_day:
        return
    stagger = 24 / target_per_day

    addons_ids_and_slugs = Addon.unfiltered.filter(
        ~Q(status=amo.STATUS_DISABLED),
        Q(promotedaddon=None) | Q(promotedaddon__group_id=NOT_PROMOTED.id),
        average_daily_users__gte=adu_limit,
        type=amo.ADDON_EXTENSION,
    ).values_list('id', 'slug', 'average_daily_users')
    count = len(addons_ids_and_slugs)
    log.info('Starting adding %s addons to %s', count, NOTABLE.name)
    for idx, (addon_id, addon_slug, adu) in enumerate(addons_ids_and_slugs):
        due_date = get_review_due_date(datetime.now() + timedelta(hours=stagger * idx))
        try:
            # We can't use update_or_create because we need to pass _due_date to save
            promo = PromotedAddon.objects.get(addon_id=addon_id)
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
            created = False
        except PromotedAddon.DoesNotExist:
            promo = PromotedAddon(addon_id=addon_id, group_id=NOTABLE.id)
            created = True
        promo.save(_due_date=due_date)

        log.info(
            '%s addon id[%s], slug[%s], with ADU[%s] to %s.',
            ('Adding' if created else 'Updating'),
            addon_id,
            addon_slug,
            adu,
            NOTABLE.name,
        )
    log.info('Done adding %s addons to %s', count, NOTABLE.name)
