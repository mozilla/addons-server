from django.db.models import Sum

import elasticutils
import pyes.exceptions as pyes

import amo
from stats.models import Contribution


def extract_installed_count(installed):
    date = installed.created.date()
    return {'date': date,
            'addon': installed.addon_id,
            'count': installed.__class__.objects.filter(
                created__year=date.year,
                created__month=date.month,
                created__day=date.day).count()}


def extract_contribution_counts(contribution):
    """
    number of contributions (sales) per app/day
    revenue per app/day
    """
    addon_id = contribution['addon']
    date = contribution['created']
    return {
        'date': date,
        'addon': addon_id,
        'count': Contribution.objects.filter(
            addon__id=addon_id,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0,
        'revenue': Contribution.objects.filter(
            addon__id=addon_id,
            type=amo.CONTRIB_PURCHASE,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).aggregate(Sum('amount'))['amount__sum']
            or 0,
        'refunds': Contribution.objects.filter(
            addon__id=addon_id,
            refund__isnull=False,
            uuid__isnull=False,
            created__year=date.year,
            created__month=date.month,
            created__day=date.day).count() or 0
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
