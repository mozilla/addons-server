from django.db.models import Count, Sum

import elasticutils
import pyes.exceptions as pyes

import amo
from stats.models import Contribution
from mkt.webapps.models import Installed


def get_finance_total(qs, addon):
    """
    sales per app
    revenue per app
    refunds per app
    """
    revenue = (qs.values('addon').filter(refund=None).
               annotate(revenue=Sum('amount')))[0]
    sales = (qs.values('addon').filter(refund=None).
             annotate(sales=Count('id')))[0]
    refunds = (qs.filter(refund__isnull=False).
               values('addon').annotate(refunds=Count('id')))[0]
    return {
        'addon': addon,
        'count': sales['sales'],
        'revenue': revenue['revenue'],
        'refunds': refunds['refunds'],
    }


def get_finance_total_by_src(qs, addon, source):
    """
    sales per app by src
    revenue per app by src
    refunds per app by src
    """
    revenues = (qs.filter(source=source, refund=None).values('addon').
                annotate(revenue=Sum('amount'))[0])
    sales = (qs.filter(source=source, refund=None).values('addon').
             annotate(sales=Count('id'))[0])
    refunds = (qs.filter(source=source, refund__isnull=False).
               values('addon').annotate(refunds=Count('id'))[0])
    return {
        'addon': addon,
        'source': source,
        'count': sales['sales'],
        'revenue': revenues['revenue'],
        'refunds': refunds['refunds'],
    }


def get_finance_total_by_currency(qs, addon, currency):
    """
    sales per app by currency
    revenue per app by currency
    refunds per app by currency
    """
    revenues = (qs.filter(currency=currency, refund=None).
                values('addon').annotate(revenue=Sum('amount'))[0])
    sales = (qs.filter(currency=currency, refund=None)
             .values('addon').annotate(sales=Count('id'))[0])
    refunds = (qs.filter(currency=currency, refund__isnull=False).
               values('addon').annotate(refunds=Count('id'))[0])
    return {
        'addon': addon,
        'currency': currency,
        'count': sales['sales'],
        'revenue': revenues['revenue'],
        'refunds': refunds['refunds'],
    }


def get_finance_total_inapp(qs, addon, inapp_name):
    """
    sales per in-app
    revenue per in-app
    refunds per in-app
    """
    revenue = (qs.filter(contribution__refund=None).
               values('config__addon').annotate(
               revenue=Sum('contribution__amount')))[0]
    sales = (qs.filter(contribution__refund=None).
             values('config__addon').
             annotate(sales=Count('id')))[0]
    refunds = (qs.filter(contribution__refund__isnull=False).
               values('config__addon').annotate(refunds=Count('id')))[0]
    return {
        'addon': addon,
        'inapp': inapp_name,
        'count': sales['sales'],
        'revenue': revenue['revenue'],
        'refunds': refunds['refunds'],
    }


def get_finance_total_inapp_by_currency(qs, addon, inapp_name, currency):
    """
    sales per in-app by currency
    revenue per in-app by currency
    refunds per in-app by currency
    """
    revenues = (qs.filter(contribution__currency=currency,
                          contribution__refund=None).
                values('config__addon').
                annotate(revenue=Sum('contribution__amount')))[0]
    sales = (qs.filter(contribution__currency=currency,
                       contribution__refund=None).
             values('config__addon').annotate(sales=Count('id')))[0]
    refunds = (qs.filter(contribution__currency=currency,
                         contribution__refund__isnull=False).
               values('config__addon').
               annotate(refunds=Count('id')))[0]
    return {
        'addon': addon,
        'inapp': inapp_name,
        'currency': currency,
        'count': sales['sales'],
        'revenue': revenues['revenue'],
        'refunds': refunds['refunds'],
    }


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
        'revenue': Contribution.objects.filter(
            addon__id=addon_id,
            refund=None,
            type=amo.CONTRIB_PURCHASE,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).aggregate(Sum('amount'))['amount__sum']
            or 0,
        'refunds': Contribution.objects.filter(
            addon__id=addon_id,
            refund__isnull=False,
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
    es = elasticutils.get_es()
    for model in [Contribution]:
        index = model._get_index()
        try:
            es.create_index_if_missing(index)
        except pyes.ElasticSearchException:
            pass

        mapping = {
            'properties': {
                'id': {'type': 'long'},
                'count': {'type': 'long'},
                'data': {'dynamic': 'true',
                         'properties': {
                            'v': {'type': 'long'},
                            'k': {'type': 'string'}
                        }
                },
                'date': {'format': 'dateOptionalTime',
                         'type': 'date'}
            }
        }
        es.put_mapping(model._meta.db_table, mapping,
                       model._get_index())
