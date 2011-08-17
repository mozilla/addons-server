import collections
import logging

from django.db.models import Sum, Max

import cronjobs
import elasticutils
import redisutils

import amo
import amo.utils
from addons.models import Addon
from stats.models import UpdateCount

from .models import AppCompat

log = logging.getLogger('z.compat')


@cronjobs.register
def compatibility_report():
    redis = redisutils.connections['master']
    docs = collections.defaultdict(dict)

    # Gather all the data for the index.
    for app in amo.APP_USAGE:
        log.info(u'Making compat report for %s.' % app.pretty)
        latest = UpdateCount.objects.aggregate(d=Max('date'))['d']
        qs = UpdateCount.objects.filter(addon__appsupport__app=app.id,
                                        addon__disabled_by_user=False,
                                        addon__status__in=amo.VALID_STATUSES,
                                        addon___current_version__isnull=False,
                                        date=latest).order_by('-count')
        total = qs.aggregate(Sum('count'))['count__sum']
        redis.hset('compat:%s' % app.id, 'total', total)
        adus = 0

        updates = dict(qs.values_list('addon', 'count'))
        for chunk in amo.utils.chunked(updates.items(), 50):
            chunk = dict(chunk)
            for addon in Addon.objects.filter(id__in=chunk):
                doc = docs[addon.id]
                doc.update(id=addon.id, slug=addon.slug, binary=addon.binary,
                           name=unicode(addon.name), created=addon.created)
                doc.setdefault('usage', {})[app.id] = updates[addon.id]

                if app not in addon.compatible_apps:
                    continue
                compat = addon.compatible_apps[app]
                d = {'min': compat.min.version_int,
                     'max': compat.max.version_int}
                doc.setdefault('support', {})[app.id] = d
                doc.setdefault('max_version', {})[app.id] = compat.max.version
                doc['top_95'] = adus > .95 * total

            adus += sum(chunk.values())

    # Send it all to the index.
    for chunk in amo.utils.chunked(docs.values(), 150):
        for doc in chunk:
            AppCompat.index(doc, id=doc['id'], bulk=True)
        elasticutils.get_es().flush_bulk(forced=True)
