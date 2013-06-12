from constants.payments import PAYMENT_METHOD_CARD

from market.models import PriceCurrency
from mkt.constants import regions


def run():
    for tier in ['0.10', '0.25', '0.50']:
        try:
            pc = PriceCurrency.objects.get(tier__price=tier,
                                           region=regions.CO.id)
        except PriceCurrency.DoesNotExist:
            print 'Skipping deleting PriceCurrency of {0} for CO'.format(tier)
            continue

        pc.delete()
        print 'Deleted PriceCurrency of {0} for CO'.format(tier)

    for tier in ['6.99', '9.99', '12.49', '14.99', '19.99', '24.99', '29.99']:
        try:
            pc = PriceCurrency.objects.get(tier__price=tier,
                                           region=regions.CO.id)
        except PriceCurrency.DoesNotExist:
            print 'Skipping modifying PriceCurrency of {0} for CO'.format(tier)
            continue

        pc.method = PAYMENT_METHOD_CARD
        pc.save()
