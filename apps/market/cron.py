from datetime import datetime, timedelta

import commonware.log
import cronjobs

from django.conf import settings
from django.db.models import Count

from addons.models import Addon, AddonUser
import amo
from amo.utils import chunked, send_mail_jinja
from market.models import AddonPremium, Refund
from devhub.models import ActivityLog

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


@cronjobs.register
def mkt_gc(**kw):
    """Site-wide garbage collections."""

    days_ago = lambda days: datetime.today() - timedelta(days=days)

    log.debug('Collecting data to delete')
    logs = (ActivityLog.objects.filter(created__lt=days_ago(90))
            .exclude(action__in=amo.LOG_KEEP).values_list('id', flat=True))

    for chunk in chunked(logs, 100):
        chunk.sort()
        log.debug('Deleting log entries: %s' % str(chunk))
        amo.tasks.delete_logs.delay(chunk)
