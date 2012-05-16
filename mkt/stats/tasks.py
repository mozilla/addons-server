from collections import defaultdict

from django.db.models import Sum, Count

from celeryutils import task
import commonware.log
import elasticutils

from . import search
from stats.models import Contribution

log = commonware.log.getLogger('z.task')


@task
def index_addon_aggregate_contributions(addons, **kw):
    """
    Aggregates stats from all of the contributions for a given addon
    """
    es = elasticutils.get_es()
    log.info('Aggregating total contribution stats for %s addons' %
        len(addons))
    try:
        for addon in addons:
            # Only count uuid=None; those are verified transactions.
            qs = Contribution.objects.filter(addon__in=addons, uuid=None)

            # Create lists of annotated dicts [{'addon':1, 'revenue':5}...]
            revenues = qs.values('addon').annotate(revenue=Sum('amount'))
            sales = qs.values('addon').annotate(sales=Count('id'))
            refunds = (qs.filter(refund__isnull=False).
                values('addon').annotate(refunds=Count('id')))

            # Loop over revenue, sales, refunds.
            data_dict = defaultdict(lambda: defaultdict(dict))
            for revenue in revenues:
                data_dict[str(
                    revenue['addon'])]['revenue'] = revenue['revenue']
            for sale in sales:
                data_dict[str(sale['addon'])]['sales'] = sale['sales']
            for refund in refunds:
                data_dict[str(refund['addon'])]['refunds'] = refund['refunds']
            for addon, addon_dict in data_dict.iteritems():
                data = {
                    'addon': addon,
                    'count': addon_dict['sales'],
                    'revenue': addon_dict['revenue'],
                    'refunds': addon_dict['refunds'],
                }
                Contribution.index(data, bulk=True, id=addon)

            es.flush_bulk(forced=True)
    except Exception, exc:
        index_addon_aggregate_contributions.retry(args=[addons], exc=exc)
        raise


@task
def index_installed_counts(ids, **kw):
    from mkt.webapps.models import Installed

    es = elasticutils.get_es()
    qs = Installed.objects.filter(id__in=set(ids))
    if qs.exists():
        log.info('Indexing %s installed counts: %s'
                 % (len(qs), qs[0].created))
    try:
        for installed in qs:
            addon_id = installed.addon_id
            key = '%s-%s' % (addon_id, installed.created)
            data = search.extract_installed_count(installed)
            Installed.index(data, bulk=True, id=key)
        es.flush_bulk(forced=True)
    except Exception, exc:
        index_installed_counts.retry(args=[ids], exc=exc)
        raise


@task
def index_contribution_counts(ids, **kw):
    """
    Contribution stats by addon-date unique pair Uses a nested
    dictionary to not index duplicate contribution with same addon/date
    pairs. For each addon-date, it stores the addon in the dict as a top
    level key with a dict as its value. And it stores the date in the
    addon's dict as a second level key. To check if an addon-date pair has
    been already index, it looks up the dict[addon][date] to see if the
    key exists.
    """
    es = elasticutils.get_es()
    qs = (Contribution.objects.filter(id__in=ids)
          .order_by('created').values('addon', 'created'))

    try:
        addons_dates = defaultdict(lambda: defaultdict(dict))
        for contribution in qs:
            addon = contribution['addon']
            date = contribution['created'].strftime('%Y%m%d')

            # date for addon not processed, index it and give it key
            if not date in addons_dates[addon]:
                key = '%s-%s' % (addon, date)
                data = search.extract_contribution_counts(contribution)
                Contribution.index(data, bulk=True, id=key)
                addons_dates[addon][date] = 0

        if qs:
            log.info('Indexed %s addons/apps for contribution stats: %s' %
                     (len(addons_dates), qs[0]['created']))
        es.flush_bulk(forced=True)
    except Exception, exc:
        index_contribution_counts.retry(args=[ids], exc=exc)
        raise
