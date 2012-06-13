from django.db.models import Count, Sum

import elasticutils
import pyes.exceptions as pyes

import amo
from mkt.webapps.models import Installed
from stats.models import Contribution


def get_finance_total(qs, addon):
    """
    sales per app
    revenue per app
    refunds per app
    """
    revenue = (qs.values('addon').filter(refund=None).
               annotate(revenue=Sum('amount')))
    sales = (qs.values('addon').filter(refund=None).
             annotate(sales=Count('id')))
    refunds = (qs.filter(refund__isnull=False).
               values('addon').annotate(refunds=Count('id')))
    return {
        'addon': addon,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': revenue[0]['revenue'] if revenue.count() else 0,
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }


def get_finance_total_by_src(qs, addon, source=''):
    """
    sales per app by src
    revenue per app by src
    refunds per app by src
    """
    revenues = (qs.filter(source=source, refund=None).values('addon').
                annotate(revenue=Sum('amount')))
    sales = (qs.filter(source=source, refund=None).values('addon').
             annotate(sales=Count('id')))
    refunds = (qs.filter(source=source, refund__isnull=False).
               values('addon').annotate(refunds=Count('id')))
    return {
        'addon': addon,
        'source': source,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': revenues[0]['revenue'] if revenues.count() else 0,
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }


def get_finance_total_by_currency(qs, addon, currency=''):
    """
    sales per app by currency
    revenue per app by currency
    refunds per app by currency
    """
    revenues = (qs.filter(currency=currency, refund=None).
                values('addon').annotate(revenue=Sum('amount')))
    sales = (qs.filter(currency=currency, refund=None)
             .values('addon').annotate(sales=Count('id')))
    refunds = (qs.filter(currency=currency, refund__isnull=False).
               values('addon').annotate(refunds=Count('id')))
    return {
        'addon': addon,
        'currency': currency,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': revenues[0]['revenue'] if revenues.count() else 0,
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }


def get_finance_total_inapp(qs, addon, inapp_name=''):
    """
    sales per in-app
    revenue per in-app
    refunds per in-app
    """
    revenue = (qs.filter(contribution__refund=None).
               values('config__addon').annotate(
               revenue=Sum('contribution__amount')))
    sales = (qs.filter(contribution__refund=None).
             values('config__addon').
             annotate(sales=Count('id')))
    refunds = (qs.filter(contribution__refund__isnull=False).
               values('config__addon').annotate(refunds=Count('id')))
    return {
        'addon': addon,
        'inapp': inapp_name,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': revenue[0]['revenue'] if revenue.count() else 0,
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
    }


def get_finance_total_inapp_by_currency(qs, addon, inapp_name='', currency=''):
    """
    sales per in-app by currency
    revenue per in-app by currency
    refunds per in-app by currency
    """
    revenues = (qs.filter(contribution__currency=currency,
                          contribution__refund=None).
                values('config__addon').
                annotate(revenue=Sum('contribution__amount')))
    sales = (qs.filter(contribution__currency=currency,
                       contribution__refund=None).
             values('config__addon').annotate(sales=Count('id')))
    refunds = (qs.filter(contribution__currency=currency,
                         contribution__refund__isnull=False).
               values('config__addon').
               annotate(refunds=Count('id')))
    return {
        'addon': addon,
        'inapp': inapp_name,
        'currency': currency,
        'count': sales[0]['sales'] if sales.count() else 0,
        'revenue': revenues[0]['revenue'] if revenues.count() else 0,
        'refunds': refunds[0]['refunds'] if refunds.count() else 0,
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
    """
    Define explicit ES mappings for models. If a field is not explicitly
    defined and a field is inserted, ES will dynamically guess the type and
    insert it, in a schemaless manner.
    """
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
                'date': {'format': 'dateOptionalTime',
                         'type': 'date'},
                'count': {'type': 'long'},
            }
        }

        # Try to tell ES not to 'analyze' the field to querying with hyphens
        # and lowercase letters.
        if model == Contribution:
            mapping['properties']['currency'] = {'type': 'string',
                                                 'index': 'not_analyzed'}
            mapping['properties']['source'] = {'type': 'string',
                                               'index': 'not_analyzed'}
            mapping['properties']['inapp'] = {'type': 'string',
                                              'index': 'not_analyzed'}

        es.put_mapping(model._meta.db_table, mapping,
                       model._get_index())
