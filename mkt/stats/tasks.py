from collections import defaultdict

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
        # Get all contributions for given add-on.
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
            continue
        try:
            key = ord_word('tot' + str(addon))
            data = search.get_finance_total(qs, addon)
            if not already_indexed(Contribution, data):
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
        # Get all contributions for given add-on.
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs:
            continue

        # Get list of distinct sources.
        sources = [src[0] for src in
                   qs.distinct('source').values_list('source')]

        for source in sources:
            try:
                key = ord_word('src' + str(source) + str(addon))
                data = search.get_finance_total_by_src(qs, addon, source)
                if not already_indexed(Contribution, data):
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
        # Get all contributions for given add-on.
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
            continue

        # Get list of distinct currencies.
        currencies = [currency[0] for currency in
                      qs.distinct('currency').values_list('currency')]

        for currency in currencies:
            try:
                key = ord_word('cur' + currency.lower() + str(addon))
                data = search.get_finance_total_by_currency(
                    qs, addon, currency)
                if not already_indexed(Contribution, data):
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

    # Get contributions.
    qs = (Contribution.objects.filter(id__in=ids)
          .order_by('created').values('addon', 'created'))
    log.info('[%s] Indexing %s contributions for daily stats.' %
             (qs[0]['created'], len(ids)))

    addons_dates = defaultdict(lambda: defaultdict(dict))
    for contribution in qs:
        addon = contribution['addon']
        date = contribution['created'].strftime('%Y%m%d')

        try:
            # Date for add-on not processed, index it and give it key.
            if not date in addons_dates[addon]:
                key = ord_word('fin' + str(date))
                data = search.get_finance_daily(contribution)
                if not already_indexed(Contribution, data):
                    Contribution.index(data, bulk=True, id=key)
                addons_dates[addon][date] = 0
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

            try:
                key = ord_word('totinapp' + str(inapp))
                data = search.get_finance_total_inapp(qs, inapp)
                if not already_indexed(InappPayment, data):
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
                try:
                    key = ord_word('curinapp' + currency.lower() + str(addon))
                    data = search.get_finance_total_inapp_by_currency(
                        qs, inapp, currency)
                    if not already_indexed(InappPayment, data):
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
    # Get Installed's
    qs = (Installed.objects.filter(id__in=set(ids)).
        order_by('-created').values('addon', 'created'))
    log.info('[%s] Indexing %s installed counts for daily stats.' %
             (qs[0]['created'], len(qs)))

    addons_dates = defaultdict(lambda: defaultdict(dict))
    for installed in qs:
        addon = installed['addon']
        date = installed['created'].strftime('%Y%m%d')

        try:
            if not date in addons_dates[addon]:
                key = ord_word('ins' + str(date))
                data = search.get_installed_daily(installed)
                if not already_indexed(Installed, data):
                    Installed.index(data, bulk=True, id=key)
                addons_dates[addon][date] = 0
            es.flush_bulk(forced=True)
        except Exception, exc:
            index_installed_daily.retry(args=[ids], exc=exc)
            raise


def ord_word(word):
    """
    Convert an alphanumeric string to its ASCII values, used for ES keys.
    """
    return ''.join([str(ord(letter)) for letter in word])


def already_indexed(model, data):
    """
    Bug 759924
    Checks that data is not being indexed twice.
    """
    # Handle the weird 'have to query in lower-case for ES' thing.
    for k, v in data.iteritems():
        try:
            data[k] = v.lower()
        except AttributeError:
            continue

    # Cast any datetimes to date.
    if 'date' in data:
        try:
            data['date'] = data['date'].date()
        except AttributeError:
            pass

    if list(model.search().filter(**data).values_dict(data.keys()[0])):
        return True
    return False
