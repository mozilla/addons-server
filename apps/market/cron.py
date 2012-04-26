from datetime import datetime, timedelta

import commonware.log
import cronjobs

from django.conf import settings
from django.db.models import Count

from addons.models import Addon, AddonUser
import amo
from amo.utils import send_mail_jinja
from market.models import AddonPremium, Refund

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
def mail_pending_refunds():
    # First find all the pending refunds and the addons for them.
    pending = dict((Refund.objects.filter(status=amo.REFUND_PENDING)
                                  .values_list('contribution__addon_id')
                                  .annotate(Count('id'))))
    if not pending:
        log.info('No refunds to email')
        return
    log.info('Mailing pending refunds: %s refunds found' % len(pending))

    # Find all owners of those addons.
    from mkt import settings as mkt_settings
    users = (AddonUser.objects.filter(role=amo.AUTHOR_ROLE_OWNER,
                                      addon__in=pending.keys())
                              .values_list('addon_id', 'user__email'))

    # Group up the owners. An owner could have more than one addon and each
    # addon can have more than one owner.
    owners = {}
    for addon_id, email in users:
        owners.setdefault(email, [])
        owners[email].append(addon_id)

    # Send the emails out.
    for owner, addon_ids in owners.items():
        log.info('Sending refund emails to: %s about %s' %
                 (email, ', '.join([str(i) for i in addon_ids])))
        addons = Addon.objects.filter(pk__in=addon_ids)
        is_webapp = addons[0].is_webapp()
        site_url = mkt_settings.SITE_URL if is_webapp else settings.SITE_URL
        ctx = {'addons': addons, 'refunds': pending, 'site_url': site_url}
        from_email = (settings.NOBODY_EMAIL if is_webapp
                                            else mkt_settings.NOBODY_EMAIL)
        send_mail_jinja('Pending refund requests at the Mozilla Marketplace',
                        'market/emails/refund-nag.txt', ctx,
                        from_email=from_email, recipient_list=[owner])
