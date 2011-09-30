import logging
from collections import defaultdict

from django.conf import settings
from django.db.models import Max

import cronjobs
import elasticutils
import redisutils

import amo
import amo.utils
from addons.models import Addon
from stats.models import UpdateCount
from versions.compare import version_int as vint

from .models import AppCompat

log = logging.getLogger('z.compat')


@cronjobs.register
def compatibility_report():
    redis = redisutils.connections['master']
    docs = defaultdict(dict)

    # Gather all the data for the index.
    for app in amo.APP_USAGE:
        log.info(u'Making compat report for %s.' % app.pretty)
        latest = UpdateCount.objects.aggregate(d=Max('date'))['d']
        qs = UpdateCount.objects.filter(addon__appsupport__app=app.id,
                                        addon__disabled_by_user=False,
                                        addon__status__in=amo.VALID_STATUSES,
                                        addon___current_version__isnull=False,
                                        date=latest)

        updates = dict(qs.values_list('addon', 'count'))
        for chunk in amo.utils.chunked(updates.items(), 50):
            chunk = dict(chunk)
            for addon in Addon.objects.filter(id__in=chunk):
                doc = docs[addon.id]
                doc.update(id=addon.id, slug=addon.slug, binary=addon.binary,
                           name=unicode(addon.name), created=addon.created)
                doc['count'] = chunk[addon.id]
                doc.setdefault('top_95',
                               defaultdict(lambda: defaultdict(dict)))
                doc.setdefault('top_95_all', {})
                doc.setdefault('usage', {})[app.id] = updates[addon.id]

                if app not in addon.compatible_apps:
                    continue
                compat = addon.compatible_apps[app]
                d = {'min': compat.min.version_int,
                     'max': compat.max.version_int}
                doc.setdefault('support', {})[app.id] = d
                doc.setdefault('max_version', {})[app.id] = compat.max.version

        total = sum(updates.values())
        # Remember the total so we can show % of usage later.
        redis.hset('compat:%s' % app.id, 'total', total)

        # Figure out which add-ons are in the top 95% for this app.
        running_total = 0
        for addon, count in sorted(updates.items(), key=lambda x: x[1]):
            running_total += count
            if 'top_95_all' not in docs[addon]:
                print docs[addon]
            docs[addon]['top_95_all'][app.id] = running_total < (.95 * total)

    # Mark the top 95% of add-ons compatible with the previous version for each
    # app + version combo.
    for compat in settings.COMPAT:
        app, ver = compat['app'], vint(compat['previous'])
        # Find all the docs that have a max_version compatible with ver.
        supported = [doc for doc in docs.values()
                     if app in doc.get('support', {})
                        and doc['support'][app]['max'] >= ver]
        # Sort by count so we can get the top 95% most-used add-ons.
        supported = sorted(supported, key=lambda d: d['count'])
        total = sum(doc['count'] for doc in supported)
        # Figure out which add-ons are in the top 95% for this app + version.
        running_total = 0
        for doc in supported:
            running_total += doc['count']
            doc['top_95'][app][ver] = running_total < (.95 * total)

    # Send it all to the index.
    for chunk in amo.utils.chunked(docs.values(), 150):
        for doc in chunk:
            AppCompat.index(doc, id=doc['id'], bulk=True)
        elasticutils.get_es().flush_bulk(forced=True)
