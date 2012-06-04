from collections import defaultdict

from django.db.models import Sum, Count

from celeryutils import task
import commonware.log
import elasticutils

from . import search
from mkt.inapp_pay.models import InappConfig, InappPayment
from stats.models import Contribution

log = commonware.log.getLogger('z.task')


@task
def index_finance_total(addons, **kw):
    """
    Aggregates financial stats from all of the contributions for a given app.
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial stats for %s apps.' %
              len(addons))

    for addon in addons:
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
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
        try:
            key = ord_word('tot' + str(addon))
            Contribution.index(data, bulk=True, id=key)
            es.flush_bulk(forced=True)
        except Exception, exc:
            index_finance_total.retry(args=[addons], exc=exc)
            raise


@task
def index_finance_total_by_src(addons, **kw):
    """
    Bug 758059
    Total finance stats, source breakdown.
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial stats by source for %s apps.' %
              len(addons))

    for addon in addons:
        qs = Contribution.objects.filter(addon=addon, uuid=None)
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
            try:
                key = ord_word('src' + str(source) + str(addon))
                Contribution.index(data, bulk=True, id=key)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_by_src.retry(args=[addons], exc=exc)
                raise


@task
def index_finance_total_by_currency(addons, **kw):
    """
    Bug 757581
    Total finance stats, currency breakdown.
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial stats by currency for %s apps.' %
              len(addons))

    for addon in addons:
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
            continue

        # Get list of distinct currencies.
        currencies = [currency[0] for currency in
                      qs.distinct('currency').values_list('currency')]
        # Get revenue, sales, refunds by currency.
        for currency in currencies:
            revenues = (qs.filter(currency=currency).values('addon').
                        annotate(revenue=Sum('amount'))[0])
            sales = (qs.filter(currency=currency).values('addon').
                     annotate(sales=Count('id'))[0])
            refunds = (qs.filter(currency=currency, refund__isnull=False).
                       values('addon').annotate(refunds=Count('id'))[0])
            data = {
                'addon': addon,
                'currency': currency,
                'count': sales['sales'],
                'revenue': revenues['revenue'],
                'refunds': refunds['refunds'],
            }
            try:
                key = ord_word('cur' + currency.lower() + str(addon))
                Contribution.index(data, bulk=True, id=key)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_by_currency.retry(args=[addons], exc=exc)
                raise


@task
def index_finance_daily(ids, **kw):
    """
    Bug 748015
    Takes a list of Contribution ids and uses its addon and date fields to
    index stats for that day.

    Contribution stats by addon-date unique pair. Uses a nested
    dictionary to not index duplicate contribution with same addon/date
    pairs. For each addon-date, it stores the addon in the dict as a top
    level key with a dict as its value. And it stores the date in the
    add-on's dict as a second level key. To check if an addon-date pair has
    been already index, it looks up the dict[addon][date] to see if the
    key exists.

    ids -- ids of apps.stats.Contribution objects
    """
    es = elasticutils.get_es()
    qs = (Contribution.objects.filter(id__in=ids)
          .order_by('created').values('addon', 'created'))

    addons_dates = defaultdict(lambda: defaultdict(dict))
    for contribution in qs:
        addon = contribution['addon']
        date = contribution['created'].strftime('%Y%m%d')

    try:
        # Date for add-on not processed, index it and give it key.
        if not date in addons_dates[addon]:
            data = search.extract_contributions_daily(contribution)
            key = ord_word('fin' + str(date))
            Contribution.index(data, bulk=True, id=key)
            addons_dates[addon][date] = 0
        if qs:
            log.info('[%s] Indexing %s contributions for daily stats.' %
                     (qs[0]['created'], len(addons_dates)))
        es.flush_bulk(forced=True)
    except Exception, exc:
        index_finance_daily.retry(args=[ids], exc=exc)
        raise


@task
def index_finance_total_inapp(addons, **kw):
    """
    Bug 758071
    Aggregates financial stats from all of the contributions for in-apps.
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial in-app stats for %s apps.' %
              len(addons))

    for addon in addons:
        # Get all in-apps for given addon.
        inapps = InappConfig.objects.filter(addon=addon)

        for inapp in inapps:
            # Get all in-app payments for given in-app.
            qs = InappPayment.objects.filter(config=inapp,
                                             contribution__uuid=None)
            if not qs.exists():
                continue

            # Get total revenue, sales, refunds for given in-app.
            revenue = (qs.values('config__addon').annotate(
                       revenue=Sum('contribution__amount')))[0]
            sales = qs.values('config__addon').annotate(sales=Count('id'))[0]
            refunds = (qs.filter(contribution__refund__isnull=False).
                       values('config__addon').
                       annotate(refunds=Count('id')))[0]
            data = {
                'addon': addon,
                'inapp': inapp.id,
                'count': sales['sales'],
                'revenue': revenue['revenue'],
                'refunds': refunds['refunds'],
            }
            try:
                key = ord_word('totinapp' + str(inapp))
                InappPayment.index(data, bulk=True, id=key)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_inapp.retry(args=[addons], exc=exc)
                raise


@task
def index_finance_total_inapp_by_currency(addons, **kw):
    """
    Bug 758071
    Total finance in-app stats, currency breakdown.
    """
    es = elasticutils.get_es()
    log.info('Indexing total financial in-app stats by currency for %s apps.' %
              len(addons))

    for addon in addons:
        # Get all in-apps for given addon.
        inapps = InappConfig.objects.filter(addon=addon)

        for inapp in inapps:
            # Get all in-app payments for given in-app.
            qs = InappPayment.objects.filter(config=inapp,
                                             contribution__uuid=None)
            if not qs.exists():
                continue

            # Get a list of distinct currencies for given in-app.
            currencies = [currency[0] for currency in
                          qs.distinct('contribution__currency').
                          values_list('contribution__currency')]

            for currency in currencies:
                revenues = (qs.filter(contribution__currency=currency).
                            values('config__addon').
                            annotate(revenue=Sum('contribution__amount')))[0]
                sales = (qs.filter(contribution__currency=currency).
                         values('config__addon').
                         annotate(sales=Count('id')))[0]
                refunds = (qs.filter(contribution__currency=currency,
                                     contribution__refund__isnull=False).
                           values('config__addon').
                           annotate(refunds=Count('id')))[0]
                data = {
                    'addon': addon,
                    'inapp': inapp.id,
                    'currency': currency,
                    'count': sales['sales'],
                    'revenue': revenues['revenue'],
                    'refunds': refunds['refunds'],
                }
                try:
                    key = ord_word('curinapp' + currency.lower() + str(addon))
                    InappPayment.index(data, bulk=True, id=key)
                    es.flush_bulk(forced=True)
                except Exception, exc:
                    index_finance_total_by_currency.retry(args=[addons],
                                                          exc=exc)
                    raise


@task
def index_installed_daily(ids, **kw):
    """
    Takes a list of Installed ids and uses its addon and date fields to index
    stats for that day. Should probably check it's not indexing a day multiple
    times redundantly.
    ids -- ids of mkt.webapps.Installed objects
    """
    from mkt.webapps.models import Installed
    es = elasticutils.get_es()

    qs = Installed.objects.filter(id__in=set(ids))
    if qs.exists():
        log.info('[%s] Indexing %s installed counts for daily stats.' %
                 (qs[0].created, len(qs)))
    try:
        for installed in qs:
            data = search.extract_installed_daily(installed)
            key = ord_word('ins' + str(installed.created))
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
