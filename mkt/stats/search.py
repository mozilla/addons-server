from decimal import Decimal

from django.db.models import Count, Q, Sum

import elasticutils.contrib.django as elasticutils

import amo
from amo.utils import create_es_index_if_missing
from mkt import MKT_CUT
from mkt.inapp_pay.models import InappPayment
from mkt.webapps.models import Installed
from stats.models import Contribution


def get_finance_total(qs, addon, field=None, **kwargs):
    """
    sales/revenue/refunds per app overall
    field -- breakdown field name contained by kwargs
    """
    q = Q()
    if field:
        kwargs_copy = {field: kwargs[field]}
        q = handle_kwargs(q, field, kwargs)

    revenue = (qs.values('addon').filter(q, refund=None, **kwargs).
               annotate(revenue=Sum('price_tier__price')))
    sales = (qs.values('addon').filter(q, refund=None, **kwargs).
             annotate(sales=Count('id')))
    refunds = (qs.filter(q, refund__isnull=False, **kwargs).
               values('addon').annotate(refunds=Count('id')))
    document = {
        'addon': addon,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': cut(revenue[0]['revenue'] if revenue.count() else 0),
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }
    if field:
        # Edge case, handle None values.
        if kwargs_copy[field] == None:
            kwargs_copy[field] = ''
        document[field] = kwargs_copy[field]

        # Non-USD-normalized revenue, calculated from currency's amount rather
        # than price tier.
        if field == 'currency':
            document['revenue_non_normalized'] = cut(qs.values('addon')
                .filter(q, refund=None, **kwargs)
                .annotate(revenue=Sum('amount'))
                [0]['revenue'] if revenue.count() else 0)

    return document


def get_finance_total_inapp(qs, addon, inapp_name='', field=None, **kwargs):
    """
    sales/revenue/refunds per in-app overall
    field -- breakdown field name contained by kwargs
    """
    q = Q()
    if field:
        kwargs_copy = {field: kwargs[field]}
        q = handle_kwargs(q, field, kwargs, join_field='contribution__')

    revenue = (qs.filter(q, contribution__refund=None, **kwargs).
               values('config__addon').annotate(
               revenue=Sum('contribution__price_tier__price')))
    sales = (qs.filter(q, contribution__refund=None, **kwargs).
             values('config__addon').
             annotate(sales=Count('id')))
    refunds = (qs.filter(q, contribution__refund__isnull=False, **kwargs).
               values('config__addon').annotate(refunds=Count('id')))
    document = {
        'addon': addon,
        'inapp': inapp_name,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': cut(revenue[0]['revenue'] if revenue.count() else 0),
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }
    if field:
        # Edge case, handle None values.
        if kwargs_copy[field] == None:
            kwargs_copy[field] = ''
        document[field] = kwargs_copy[field]

        # Non-USD-normalized revenue, calculated from currency's amount rather
        # than price tier.
        if field == 'currency':
            document['revenue_non_normalized'] = cut(qs.values('config__addon')
                .filter(q, contribution__refund=None, **kwargs)
                .annotate(revenue=Sum('contribution__amount'))
            [0]['revenue'] if revenue.count() else 0)

    return document


def get_finance_daily(contribution):
    """
    sales per day
    revenue per day
    refunds per day
    """
    addon_id = contribution['addon']
    date = contribution['created'].date()
    return {
        'date': date,
        'addon': addon_id,
        'count': Contribution.objects.filter(
            addon__id=addon_id,
            refund=None,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0,
        # TODO: non-USD-normalized revenue (daily_by_currency)?
        'revenue': cut(Contribution.objects.filter(
            addon__id=addon_id,
            refund=None,
            type=amo.CONTRIB_PURCHASE,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day)
            .aggregate(revenue=Sum('price_tier__price'))['revenue']
            or 0),
        'refunds': Contribution.objects.filter(
            addon__id=addon_id,
            refund__isnull=False,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0,
    }


def get_finance_daily_inapp(payment):
    """
    sales per day for inapp
    revenue per day for inapp
    refunds per day for inapp
    """
    addon_id = payment['config__addon']
    inapp = payment['name']
    date = payment['created'].date()
    return {
        'date': date,
        'addon': addon_id,
        'inapp': inapp,
        'count': InappPayment.objects.filter(
            config__addon__id=addon_id,
            contribution__refund=None,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0,
        # TODO: non-USD-normalized revenue (daily_inapp_by_currency)?
        'revenue': cut(InappPayment.objects.filter(
            config__addon__id=addon_id,
            contribution__refund=None,
            contribution__type=amo.CONTRIB_PURCHASE,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day)
            .aggregate(rev=Sum('contribution__price_tier__price'))['rev']
            or 0),
        'refunds': InappPayment.objects.filter(
            contribution__addon__id=addon_id,
            contribution__refund__isnull=False,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0,
    }


def get_installed_daily(installed):
    """
    installs per day
    """
    addon_id = installed['addon']
    date = installed['created'].date()
    return {
        'date': date,
        'addon': addon_id,
        'count': Installed.objects.filter(
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count()
    }


def setup_mkt_indexes():
    """
    Define explicit ES mappings for models. If a field is not explicitly
    defined and a field is inserted, ES will dynamically guess the type and
    insert it, in a schemaless manner.
    """
    es = elasticutils.get_es()
    for model in [Contribution, InappPayment]:
        index = model._get_index()
        create_es_index_if_missing(index)

        mapping = {
            'properties': {
                'id': {'type': 'long'},
                'date': {'format': 'dateOptionalTime',
                         'type': 'date'},
                'count': {'type': 'long'},
                'revenue': {'type': 'double'},

                # Try to tell ES not to 'analyze' the field to querying with
                # hyphens and lowercase letters.
                'currency': {'type': 'string',
                             'index': 'not_analyzed'},
                'source': {'type': 'string',
                           'index': 'not_analyzed'},
                'inapp': {'type': 'string',
                          'index': 'not_analyzed'}
            }
        }

        es.put_mapping(model._meta.db_table, mapping,
                       model._get_index())


def cut(revenue):
    """
    Takes away Marketplace's cut from developers' revenue.
    """
    return Decimal(str(round(Decimal(str(revenue)) *
                   Decimal(str(MKT_CUT)), 2)))


def handle_kwargs(q, field, kwargs, join_field=None):
    """
    Processes kwargs to combine '' and None values and make it ready for
    filters. Returns Q object to use in filter.
    """
    if join_field:
        join_field += field
        kwargs[join_field] = kwargs[field]

    # Have '' and None have the same meaning.
    if not kwargs[field]:
        q = Q(**{field + '__in': ['', None]})
        del(kwargs[field])

    # We are using the join field to filter so get rid of the plain one.
    if join_field:
        del(kwargs[field])

    return q
