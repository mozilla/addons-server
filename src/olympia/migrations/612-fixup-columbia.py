from constants.payments import PAYMENT_METHOD_CARD

from market.models import Price, PriceCurrency
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

    for tier, amount in [('14.99', '31280.00'),
                         ('19.99', '41720.00'),
                         ('24.99', '52160.00')]:
        try:
            price = Price.objects.get(price=tier)
        except Price.DoesNotExist:
            print 'Skipping adding in {0} for CO'.format(tier)
            continue

        if not PriceCurrency.objects.filter(tier=price,
                                            region=regions.CO.id).exists():
            PriceCurrency.objects.create(region=regions.CO.id, currency='COP',
                                         price=amount, carrier=None,
                                         provider=1, tier=price)
            print 'Created {0} for CO'.format(tier)

    for tier in ['6.99', '9.99', '12.49', '14.99', '19.99', '24.99', '29.99']:
        try:
            pc = PriceCurrency.objects.get(tier__price=tier,
                                           region=regions.CO.id)
        except PriceCurrency.DoesNotExist:
            print 'Skipping modifying PriceCurrency of {0} for CO'.format(tier)
            continue

        pc.method = PAYMENT_METHOD_CARD
        pc.save()
        print 'Updated {0} for CO to card'.format(tier)
