from datetime import datetime, timedelta

import amo
import commonware.log
import cronjobs
from market.models import AddonPremium

log = commonware.log.getLogger('z.cron')

DAYS_OLD = 1


@cronjobs.register
def clean_out_addonpremium(days=DAYS_OLD):
    """Clean out premiums if the addon is not premium."""
    old = datetime.now() - timedelta(days=days)
    objs = AddonPremium.objects.filter(addon__premium_type=amo.ADDON_FREE,
                                       created__lt=old)
    log.info('Deleting %s old addonpremiums.' % objs.count())
    for obj in objs:
        log.info('Delete addonpremium %s which was created on %s' %
                 (obj.addon_id, obj.created))
        obj.delete()

