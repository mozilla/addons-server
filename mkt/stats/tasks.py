from collections import defaultdict
import copy

from celeryutils import task
import commonware.log

import amo.search
from . import search
from lib.es.utils import get_indices
from mkt.inapp_pay.models import InappPayment
from stats.models import Contribution

log = commonware.log.getLogger('z.task')


@task
def index_finance_total(addons, **kw):
    """
    Aggregates financial stats from all of the contributions for a given app.
    """
    index = kw.get('index', Contribution._get_index())
    es = amo.search.get_es()
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
            for index in get_indices(index):
                if not already_indexed(Contribution, data, index):
                    Contribution.index(data, bulk=True, id=key, index=index)
            es.flush_bulk(forced=True)
        except Exception, exc:
            index_finance_total.retry(args=[addons], exc=exc, **kw)
            raise


@task
def index_finance_total_by_src(addons, **kw):
    """
    Bug 758059
    Total finance stats, source breakdown.
    """
    index = kw.get('index', Contribution._get_index())
    es = amo.search.get_es()
    log.info('Indexing total financial stats by source for %s apps.' %
              len(addons))

    for addon in addons:
        # Get all contributions for given add-on.
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
            continue

        # Get list of distinct sources.
        sources = set(qs.values_list('source', flat=True))

        for source in sources:
            try:
                key = ord_word('src' + str(addon) + str(source))
                data = search.get_finance_total(qs, addon, 'source',
                                                source=source)
                for index in get_indices(index):
                    if not already_indexed(Contribution, data, index):
                        Contribution.index(data, bulk=True, id=key,
                                           index=index)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_by_src.retry(args=[addons], exc=exc, **kw)
                raise


@task
def index_finance_total_by_currency(addons, **kw):
    """
    Bug 757581
    Total finance stats, currency breakdown.
    """
    index = kw.get('index', Contribution._get_index())
    es = amo.search.get_es()
    log.info('Indexing total financial stats by currency for %s apps.' %
              len(addons))

    for addon in addons:
        # Get all contributions for given add-on.
        qs = Contribution.objects.filter(addon=addon, uuid=None)
        if not qs.exists():
            continue

        # Get list of distinct currencies.
        currencies = set(qs.values_list('currency', flat=True))

        for currency in currencies:
            try:
                key = ord_word('cur' + str(addon) + currency.lower())
                data = search.get_finance_total(
                    qs, addon, 'currency', currency=currency)
                for index in get_indices(index):
                    if not already_indexed(Contribution, data, index):
                        Contribution.index(data, bulk=True, id=key,
                                           index=index)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_by_currency.retry(args=[addons], exc=exc, **kw)
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
    key exists. This adds some speed up when batch processing.

    ids -- ids of apps.stats.Contribution objects
    """
    index = kw.get('index', Contribution._get_index())
    es = amo.search.get_es()

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
                key = ord_word('fin' + str(addon) + str(date))
                data = search.get_finance_daily(contribution)
                for index in get_indices(index):
                    if not already_indexed(Contribution, data, index):
                        Contribution.index(data, bulk=True, id=key,
                                           index=index)
                addons_dates[addon][date] = 0
            es.flush_bulk(forced=True)
        except Exception, exc:
            index_finance_daily.retry(args=[ids], exc=exc, **kw)
            raise


@task
def index_finance_total_inapp(addons, **kw):
    """
    Bug 758071
    Aggregates financial stats from all of the contributions for in-apps.
    """
    index = kw.get('index', InappPayment._get_index())
    es = amo.search.get_es()
    log.info('Indexing total financial in-app stats for %s apps.' %
             len(addons))

    for addon in addons:
        # Get all in-app names for given addon.
        inapps = set(InappPayment.objects.filter(config__addon=addon).
            values_list('name', flat=True))

        for inapp_name in inapps:
            # Get all in-app payments for given in-app.
            qs = InappPayment.objects.filter(name=inapp_name,
                                             contribution__uuid=None)
            if not qs.exists():
                continue

            try:
                key = ord_word('totinapp' + str(addon) + inapp_name)
                data = search.get_finance_total_inapp(qs, addon, inapp_name)
                for index in get_indices(index):
                    if not already_indexed(InappPayment, data, index):
                        InappPayment.index(data, bulk=True, id=key,
                                           index=index)
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_total_inapp.retry(args=[addons], exc=exc, **kw)
                raise


@task
def index_finance_total_inapp_by_currency(addons, **kw):
    """
    Bug 758071
    Total finance in-app stats, currency breakdown.
    """
    index = kw.get('index', InappPayment._get_index())
    es = amo.search.get_es()
    log.info('Indexing total financial in-app stats by currency for %s apps.' %
             len(addons))

    for addon in addons:
        # Get all in-app names for given addon.
        inapps = set(InappPayment.objects.filter(config__addon=addon).
            values_list('name', flat=True))

        for inapp_name in inapps:
            # Get all in-app payments for given in-app.
            qs = InappPayment.objects.filter(name=inapp_name,
                                             contribution__uuid=None)
            if not qs.exists():
                continue
            # Get a list of distinct currencies for given in-app.
            currencies = set(qs.values_list('contribution__currency',
                flat=True))

            for currency in currencies:
                try:
                    key = ord_word('curinapp' + str(addon) + inapp_name +
                                   currency.lower())
                    data = search.get_finance_total_inapp(
                        qs, addon, inapp_name, 'currency', currency=currency)
                    for index in get_indices(index):
                        if not already_indexed(InappPayment, data, index):
                            InappPayment.index(data, bulk=True, id=key,
                                               index=index)
                    es.flush_bulk(forced=True)
                except Exception, exc:
                    index_finance_total_by_currency.retry(args=[addons],
                                                          exc=exc, **kw)
                    raise


@task
def index_finance_total_inapp_by_src(addons, **kw):
    """
    Total finance in-app stats, src breakdown.
    """
    index = kw.get('index', InappPayment._get_index())
    es = amo.search.get_es()
    log.info('Indexing total financial in-app stats by src for %s apps.' %
             len(addons))

    for addon in addons:
        # Get all in-app names for given addon.
        inapps = set(InappPayment.objects.filter(config__addon=addon).
            values_list('name', flat=True))

        for inapp_name in inapps:
            # Get all in-app payments for given in-app.
            qs = InappPayment.objects.filter(name=inapp_name,
                                             contribution__uuid=None)
            if not qs.exists():
                continue
            # Get a list of distinct sources for given in-app.
            sources = set(qs.values_list('contribution__source',
                flat=True))

            for source in sources:
                try:
                    key = ord_word('srcinapp' + str(addon) + inapp_name +
                                   source.lower())
                    try:
                        data = search.get_finance_total_inapp(
                            qs, addon, inapp_name, 'source', source=source)

                        for index in get_indices(index):
                            if not already_indexed(InappPayment, data, index):
                                InappPayment.index(data, bulk=True, id=key,
                                                   index=index)
                    except Exception, e:
                        # We ignore this error for now. See #805181
                        pass

                    es.flush_bulk(forced=True)

                except Exception, exc:
                    index_finance_total_by_src.retry(args=[addons],
                                                     exc=exc, **kw)
                    raise


@task
def index_finance_daily_inapp(ids, **kw):
    """
    Similar to index_finance_daily, except for InappPayments.

    ids -- ids of mkt.stats.webapps.InappPayment objects
    """
    index = kw.get('index', InappPayment._get_index())
    es = amo.search.get_es()

    # Get contributions.
    qs = (InappPayment.objects.filter(id__in=ids)
          .order_by('created').values('name',
                                      'config__addon',
                                      'created'))
    log.info('[%s] Indexing %s in-app payments for daily stats.' %
             (qs[0]['created'], len(ids)))

    # It's defaultdicts all the way down.
    addons_inapps_dates = defaultdict(lambda: defaultdict(
        lambda: defaultdict(int)))
    for payment in qs:
        addon = payment['config__addon']
        inapp = payment['name']
        date = payment['created'].strftime('%Y%m%d')

        # Date for add-on not processed, index it and give it key.
        if not date in addons_inapps_dates[addon][inapp]:
            key = ord_word('fin%s%s%s' % (str(addon), str(inapp), str(date)))
            data = search.get_finance_daily_inapp(payment)
            try:
                if not already_indexed(InappPayment, data, index):
                    InappPayment.index(data, bulk=True, id=key, index=index)
                addons_inapps_dates[addon][inapp][date] = 0
                es.flush_bulk(forced=True)
            except Exception, exc:
                index_finance_daily_inapp.retry(args=[ids], exc=exc, **kw)
                raise


@task
def index_installed_daily(ids, **kw):
    """
    Takes a list of Installed ids and uses its addon and date fields to index
    stats for that day.
    ids -- ids of mkt.webapps.Installed objects
    """
    from mkt.webapps.models import Installed
    index = kw.get('index', Installed._get_index())
    es = amo.search.get_es()
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
                key = ord_word('ins' + str(addon) + str(date))
                data = search.get_installed_daily(installed)
                for index in get_indices(index):

                    if not already_indexed(Installed, data, index):
                        Installed.index(data, bulk=True, id=key,
                                        index=index)
                addons_dates[addon][date] = 0
            es.flush_bulk(forced=True)
        except Exception, exc:
            index_installed_daily.retry(args=[ids], exc=exc, **kw)
            raise


def ord_word(word):
    """
    Convert an alphanumeric string to its ASCII values, used for ES keys.
    """
    return ''.join([str(ord(letter)) for letter in word])


def already_indexed(model, data, index=None):
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

    filter_data = copy.deepcopy(data)

    # Search floating point number with string (bug 770037 fix attempt #100).
    if 'revenue' in filter_data:
        try:
            filter_data['revenue'] = str(filter_data['revenue'])
        except AttributeError:
            pass

    # XXX shouldn't we return True here ?
    return list(model.search(index).filter(**filter_data)
                    .values_dict(data.keys()[0]))
