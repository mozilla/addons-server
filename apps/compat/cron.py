import logging
from collections import defaultdict

from django.db.models import Count, Max

import cronjobs

import amo
import amo.search
import amo.utils
from addons.models import Addon
from search.utils import floor_version
from stats.models import UpdateCount
from versions.compare import version_int as vint
from lib.es.utils import get_indices

from .models import AppCompat, CompatReport, CompatTotals

log = logging.getLogger('z.compat')


@cronjobs.register
def compatibility_report(index=None):
    docs = defaultdict(dict)
    indices = get_indices(index)

    # Gather all the data for the index.
    for app in amo.APP_USAGE:
        versions = [c for c in amo.COMPAT if c['app'] == app.id]

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
                doc.update(id=addon.id, slug=addon.slug, guid=addon.guid,
                           binary=addon.binary_components,
                           name=unicode(addon.name), created=addon.created,
                           current_version=addon.current_version.version,
                           current_version_id=addon.current_version.pk)
                doc['count'] = chunk[addon.id]
                doc.setdefault('top_95',
                               defaultdict(lambda: defaultdict(dict)))
                doc.setdefault('top_95_all', {})
                doc.setdefault('usage', {})[app.id] = updates[addon.id]
                doc.setdefault('works', {}).setdefault(app.id, {})

                # Populate with default counts for all app versions.
                for ver in versions:
                    doc['works'][app.id][vint(ver['main'])] = {
                        'success': 0,
                        'failure': 0,
                        'total': 0,
                        'failure_ratio': 0.0,
                    }

                # Group reports by `major`.`minor` app version.
                reports = (CompatReport.objects
                           .filter(guid=addon.guid, app_guid=app.guid)
                           .values_list('app_version', 'works_properly')
                           .annotate(Count('id')))
                for ver, works_properly, cnt in reports:
                    ver = vint(floor_version(ver))
                    major = [v['main'] for v in versions
                             if vint(v['previous']) < ver <= vint(v['main'])]
                    if major:
                        w = doc['works'][app.id][vint(major[0])]
                        # Tally number of success and failure reports.
                        w['success' if works_properly else 'failure'] += cnt
                        w['total'] += cnt
                        # Calculate % of incompatibility reports.
                        w['failure_ratio'] = w['failure'] / float(w['total'])

                if app not in addon.compatible_apps:
                    continue
                compat = addon.compatible_apps[app]
                d = {'min': compat.min.version_int,
                     'max': compat.max.version_int}
                doc.setdefault('support', {})[app.id] = d
                doc.setdefault('max_version', {})[app.id] = compat.max.version

        total = sum(updates.values())
        # Remember the total so we can show % of usage later.
        compat_total, created = CompatTotals.objects.safer_get_or_create(
            app=app.id,
            defaults={'total': total})
        if not created:
            compat_total.update(total=total)

        # Figure out which add-ons are in the top 95% for this app.
        running_total = 0
        for addon, count in sorted(updates.items(), key=lambda x: x[1],
                                   reverse=True):
            running_total += count
            docs[addon]['top_95_all'][app.id] = running_total < (.95 * total)

    # Mark the top 95% of add-ons compatible with the previous version for each
    # app + version combo.
    for compat in amo.COMPAT:
        app, ver = compat['app'], vint(compat['previous'])
        # Find all the docs that have a max_version compatible with ver.
        supported = [doc for doc in docs.values()
                     if app in doc.get('support', {})
                        and doc['support'][app]['max'] >= ver]
        # Sort by count so we can get the top 95% most-used add-ons.
        supported = sorted(supported, key=lambda d: d['count'], reverse=True)
        total = sum(doc['count'] for doc in supported)
        # Figure out which add-ons are in the top 95% for this app + version.
        running_total = 0
        for doc in supported:
            running_total += doc['count']
            doc['top_95'][app][ver] = running_total < (.95 * total)

    # Send it all to the index.
    for chunk in amo.utils.chunked(docs.values(), 150):
        for doc in chunk:
            for index in indices:
                AppCompat.index(doc, id=doc['id'], refresh=False, index=index)
    es = amo.search.get_es()
    es.indices.refresh()
