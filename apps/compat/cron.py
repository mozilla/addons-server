import logging

from django.conf import settings
from django.db.models import Sum, Max

import cronjobs
import redisutils

import amo
import versions.compare as vc
from addons.models import Addon
from stats.models import UpdateCount

log = logging.getLogger('z.compat')


@cronjobs.register
def compatibility_report():
    redis = redisutils.connections['master']

    # for app in amo.APP_USAGE:
    for compat in settings.COMPAT:
        app = amo.APPS_ALL[compat['app']]
        version = compat['version']
        log.info(u'Making compat report for %s %s.' % (app.pretty, version))
        versions = (('latest', version), ('beta', version + 'b'),
                    ('alpha', compat['alpha']))

        rv = dict((k, 0) for k in dict(versions))
        rv['other'] = 0

        ignore = (amo.STATUS_NULL, amo.STATUS_DISABLED)
        qs = (Addon.objects.exclude(type=amo.ADDON_PERSONA, status__in=ignore)
              .filter(appsupport__app=app.id, name__locale='en-us'))

        latest = UpdateCount.objects.aggregate(d=Max('date'))['d']
        qs = UpdateCount.objects.filter(addon__appsupport__app=app.id,
                                        date=latest)
        total = qs.aggregate(Sum('count'))['count__sum']
        addons = list(qs.values_list('addon', 'count', 'addon__appsupport__min',
                                     'addon__appsupport__max'))

        # Count up the top 95% of addons by ADU.
        adus = 0
        for addon, count, minver, maxver in addons:
            # Don't count add-ons that weren't compatible with the previous
            # release
            if maxver < vc.version_int(compat['previous']):
                continue
            if adus < .95 * total:
                adus += count
            else:
                break
            for key, version in versions:
                if minver <= vc.version_int(version) <= maxver:
                    rv[key] += 1
                    break
            else:
                rv['other'] += 1
        log.info(u'Compat for %s %s: %s' % (app.pretty, version, rv))
        key = '%s:%s' % (app.id, version)
        redis.hmset('compat:' + key, rv)
