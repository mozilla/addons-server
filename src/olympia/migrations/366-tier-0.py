from decimal import Decimal

from market.models import Price, PriceCurrency


def run():
    tier = Price.objects.create(name='Tier 0', price=Decimal('0'), active=True)
    for currency in ['CAD', 'EUR', 'GBP', 'JPY']:
        PriceCurrency.objects.create(
            tier=tier, price=Decimal('0'), currency=currency
        )
