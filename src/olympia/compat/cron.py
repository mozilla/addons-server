from collections import defaultdict

from django.db.models import Count, Max

import elasticsearch.helpers

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo import search as amo_search
from olympia.amo.utils import chunked
from olympia.compat import FIREFOX_COMPAT
from olympia.lib.es.utils import get_indices
from olympia.search.utils import floor_version
from olympia.stats.models import UpdateCount
from olympia.versions.compare import version_int as vint

from .models import AppCompat, CompatReport, CompatTotals


def compatibility_report(index=None):
    docs = defaultdict(dict)
    indices = get_indices(index)

    # Gather all the data for the index.
    log.info(u'Generating Firefox compat report.')
    latest = UpdateCount.objects.aggregate(d=Max('date'))['d']
    qs = UpdateCount.objects.filter(addon__appsupport__app=amo.FIREFOX.id,
                                    addon__disabled_by_user=False,
                                    addon__status__in=amo.VALID_ADDON_STATUSES,
                                    addon___current_version__isnull=False,
                                    date=latest)

    updates = dict(qs.values_list('addon', 'count'))
    for chunk in chunked(updates.items(), 50):
        chunk = dict(chunk)
        for addon in Addon.objects.filter(id__in=chunk):
            if (amo.FIREFOX not in addon.compatible_apps or
                    addon.compatible_apps[amo.FIREFOX] is None):
                # Ignore this add-on if it does not have compat information
                # for Firefox.
                continue

            current_version = {
                'id': addon.current_version.pk,
                'version': addon.current_version.version,
            }
            doc = docs[addon.id]
            doc.update(id=addon.id, slug=addon.slug, guid=addon.guid,
                       binary=addon.binary_components,
                       name=unicode(addon.name), created=addon.created,
                       current_version=current_version)
            doc['count'] = chunk[addon.id]
            doc['usage'] = updates[addon.id]
            doc['top_95'] = {}

            # Populate with default counts for all versions.
            doc['works'] = {vint(version['main']): {
                'success': 0,
                'failure': 0,
                'total': 0,
                'failure_ratio': 0.0,
            } for version in FIREFOX_COMPAT}

            # Group reports by `major`.`minor` app version.
            reports = (CompatReport.objects
                       .filter(guid=addon.guid, app_guid=amo.FIREFOX.guid)
                       .values_list('app_version', 'works_properly')
                       .annotate(Count('id')))
            for ver, works_properly, cnt in reports:
                ver = vint(floor_version(ver))
                major = [v['main'] for v in FIREFOX_COMPAT
                         if vint(v['previous']) < ver <= vint(v['main'])]
                if major:
                    w = doc['works'][vint(major[0])]
                    # Tally number of success and failure reports.
                    w['success' if works_properly else 'failure'] += cnt
                    w['total'] += cnt
                    # Calculate % of incompatibility reports.
                    w['failure_ratio'] = w['failure'] / float(w['total'])

            compat = addon.compatible_apps[amo.FIREFOX]
            doc['support'] = {'min': compat.min.version_int,
                              'max': compat.max.version_int}
            doc['max_version'] = compat.max.version

    total = sum(updates.values())
    # Remember the total so we can show % of usage later.
    compat_total, created = CompatTotals.objects.safer_get_or_create(
        defaults={'total': total})
    if not created:
        compat_total.update(total=total)

    # Figure out which add-ons are in the top 95%.
    running_total = 0
    for addon, count in sorted(updates.items(), key=lambda x: x[1],
                               reverse=True):
        # Ignore the updates we skipped because of bad app compatibility.
        if addon in docs:
            running_total += count
            docs[addon]['top_95_all'] = running_total < (.95 * total)

    # Mark the top 95% of add-ons compatible with the previous version for each
    # version.
    for compat in FIREFOX_COMPAT:
        version = vint(compat['previous'])
        # Find all the docs that have a max_version compatible with version.
        supported = [compat_doc for compat_doc in docs.values()
                     if compat_doc['support']['max'] >= version]
        # Sort by count so we can get the top 95% most-used add-ons.
        supported = sorted(supported, key=lambda d: d['count'], reverse=True)
        total = sum(doc['count'] for doc in supported)
        # Figure out which add-ons are in the top 95% for this app + version.
        running_total = 0
        for doc in supported:
            running_total += doc['count']
            doc['top_95'][version] = running_total < (.95 * total)

    # Send it all to ES.
    bulk = []
    for id_, doc in docs.items():
        for index in set(indices):
            bulk.append({
                "_source": doc,
                "_id": id_,
                "_type": AppCompat.get_mapping_type(),
                "_index": index or AppCompat._get_index(),
            })

    es = amo_search.get_es()
    log.info('Bulk indexing %s compat docs on %s indices' % (
             len(docs), len(indices)))
    elasticsearch.helpers.bulk(es, bulk, chunk_size=150)
    es.indices.refresh()
