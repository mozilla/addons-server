import logging

from django.db.models import Max

import amo
import cronjobs

from .models import Addon

log = logging.getLogger('z.cron')


def _change_last_updated(next):
    # We jump through some hoops here to make sure we only change the add-ons
    # that really need it, and to invalidate properly.
    current = dict(Addon.objects.values_list('id', 'last_updated'))
    changes = {}

    for addon, last_updated in next.items():
        if current[addon] != last_updated:
            changes[addon] = last_updated

    if not changes:
        return

    log.debug('Updating %s add-ons' % len(changes))
    # Update + invalidate.
    for addon in Addon.objects.filter(id__in=changes):
        addon.last_updated = changes[addon.id]
        addon.save()


@cronjobs.register
def addon_last_updated():
    next = {}

    public = (Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                   versions__files__status=amo.STATUS_PUBLIC)
              .values('id')
              .annotate(last_updated=Max('versions__files__datestatuschanged')))

    exp = (Addon.objects.exclude(status=amo.STATUS_PUBLIC)
           .filter(versions__files__status__in=amo.VALID_STATUSES)
           .values('id')
           .annotate(last_updated=Max('versions__files__created')))

    listed = (Addon.objects.filter(status=amo.STATUS_LISTED)
              .values('id')
              .annotate(last_updated=Max('versions__created')))

    personas = (Addon.objects.filter(type=amo.ADDON_PERSONA)
                .extra(select={'last_updated': 'modified'}))

    for q in (public, exp, listed, personas):
        for addon, last_updated in q.values_list('id', 'last_updated'):
            next[addon] = last_updated

    _change_last_updated(next)

    # Get anything that didn't match above.
    other = (Addon.objects.filter(last_updated__isnull=True)
             .values_list('id', 'modified'))
    _change_last_updated(dict(other))
