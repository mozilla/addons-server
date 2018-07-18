from decimal import Decimal

from market.models import Price


tiers = [
    Decimal(x)
    for x in (
        '0.99',
        '1.99',
        '2.99',
        '3.99',
        '4.99',
        '5.99',
        '6.99',
        '7.99',
        '8.99',
        '9.99',
        '10.99',
        '11.99',
        '12.99',
        '13.99',
        '14.99',
        '15.99',
        '16.99',
        '17.99',
        '18.99',
        '19.99',
        '20.99',
        '21.99',
        '22.99',
        '23.99',
        '24.99',
        '29.99',
        '34.99',
        '39.99',
        '44.99',
        '49.99',
    )
]


def run():
    for i, price in enumerate(tiers, 1):
        Price.objects.create(price=price, name='Tier %s' % (i,))
