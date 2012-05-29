from collections import defaultdict

from django.db.models import Sum, Count

from celeryutils import task
import commonware.log
import elasticutils

from . import search
from stats.models import Contribution

log = commonware.log.getLogger('z.task')


@task
def index_finance_total(addons, **kw):
    """
    Aggregates financial stats from all of the contributions for a given app
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial stats for %s apps' %
              len(addons))
    try:
        for addon in addons:
            qs = Contribution.objects.filter(addon__in=addons, uuid=None)
            if not qs:
                continue

            # Get total revenue, sales, refunds per app.
            revenue = qs.values('addon').annotate(revenue=Sum('amount'))[0]
            sales = qs.values('addon').annotate(sales=Count('id'))[0]
            refunds = (qs.filter(refund__isnull=False).
                       values('addon').annotate(refunds=Count('id')))[0]
            data = {
                'addon': addon,
                'count': sales['sales'],
                'revenue': revenue['revenue'],
                'refunds': refunds['refunds'],
            }
            Contribution.index(data, bulk=True, id=ord_word('tot' +
                               str(addon)))
            es.flush_bulk(forced=True)
    except Exception, exc:
        index_finance_total.retry(args=[addons], exc=exc)
        raise


@task
def index_finance_total_by_src(addons, **kw):
    """
    Bug 758059
    Total finance stats, source breakdown
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial stats by source for %s apps' %
              len(addons))
    try:
        for addon in addons:
            qs = Contribution.objects.filter(addon__in=addons, uuid=None)
            if not qs:
                continue

            # Get list of distinct sources.
            sources = [src[0] for src in
                       qs.distinct('source').values_list('source')]

            # Get revenue, sales, refunds by source.
            for source in sources:
                revenues = (qs.filter(source=source).values('addon').
                            annotate(revenue=Sum('amount'))[0])
                sales = (qs.filter(source=source).values('addon').
                         annotate(sales=Count('id'))[0])
                refunds = (qs.filter(source=source, refund__isnull=False).
                           values('addon').annotate(refunds=Count('id'))[0])
                data = {
                    'addon': addon,
                    'source': source,
                    'count': sales['sales'],
                    'revenue': revenues['revenue'],
                    'refunds': refunds['refunds'],
                }
                Contribution.index(data, bulk=True, id=ord_word('src' +
                                   str(source) + str(addon)))
                es.flush_bulk(forced=True)
    except Exception, exc:
        index_finance_total_by_src.retry(args=[addons], exc=exc)
        raise


@task
def index_finance_daily(ids, **kw):
    """
    Bug 748015
    Contribution stats by addon-date unique pair. Uses a nested
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
                data = search.extract_contributions_daily(contribution)
                Contribution.index(data, bulk=True, id=key)
                addons_dates[addon][date] = 0

        if qs:
            log.info('[%s] Indexing daily financial stats for %s apps' %
                     (qs[0]['created'], len(addons_dates)))
        es.flush_bulk(forced=True)
    except Exception, exc:
        index_finance_daily.retry(args=[ids], exc=exc)
        raise


@task
def index_installed_daily(ids, **kw):
    from mkt.webapps.models import Installed

    es = elasticutils.get_es()
    qs = Installed.objects.filter(id__in=set(ids))
    if qs.exists():
        log.info('[%s] Indexing daily installed stats for %s apps'
                 % (qs[0].created, len(qs)))
    try:
        for installed in qs:
            addon_id = installed.addon_id
            key = '%s-%s' % (addon_id, installed.created)
            data = search.extract_installed_daily(installed)
            Installed.index(data, bulk=True, id=key)
        es.flush_bulk(forced=True)
    except Exception, exc:
        index_installed_daily.retry(args=[ids], exc=exc)
        raise


def ord_word(word):
    """
    Convert an alphanumeric string to its ASCII values, used for ES keys.
    """
    return ''.join([str(ord(letter)) for letter in word])
