import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.constants.promoted import NOTABLE
from olympia.promoted.models import PromotedAddon
from olympia.zadmin.models import get_config


log = olympia.core.logger.getLogger('z.promoted.cron')

ADU_LIMIT_CONFIG_KEY = 'notable-adu-threshold'


def add_high_adu_extensions_to_notable():
    """Add add-ons with high ADU to Notable promoted group."""

    adu_limit = get_config(ADU_LIMIT_CONFIG_KEY)
    if not adu_limit:
        log.info('[%s] config key not set', ADU_LIMIT_CONFIG_KEY)
        return
    addons_ids_and_slugs = (
        Addon.objects.public()
        .filter(
            average_daily_users__gte=adu_limit,
            type=amo.ADDON_EXTENSION,
            promotedaddon=None,
        )
        .values_list('id', 'slug', 'average_daily_users')
    )
    count = len(addons_ids_and_slugs)
    log.info('Starting adding %s addons to %s', count, NOTABLE.name)
    for addon_id, addon_slug, adu in addons_ids_and_slugs:
        log.info(
            'Adding addon id[%s], slug[%s], with ADU[%s] to %s.',
            addon_id,
            addon_slug,
            adu,
            NOTABLE.name,
        )
        PromotedAddon.objects.create(addon_id=addon_id, group_id=NOTABLE.id)
    log.info('Done adding %s addons to %s', count, NOTABLE.name)
