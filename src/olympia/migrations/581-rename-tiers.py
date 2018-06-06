from decimal import Decimal

from market.models import Price


tiers = """
0 0.00
1 0.10
5 0.25
7 0.50
10 0.99
20 1.99
30 2.99
40 3.99
50 4.99
60 6.99
70 9.99
80 12.49
90 14.99
100 19.99
110 24.99
120 29.99
130 39.99
140 49.99
"""


def run():
    for tier in tiers.strip().split('\n'):
        if not tier.strip():
            continue
        name, amount = tier.strip().split(' ')
        try:
            tier = Price.objects.get(price=Decimal(amount))
        except Price.DoesNotExist:
            print('Tier not found: %s' % amount)
            continue

        tier.name = name
        tier.save()
        print('Tier changed: %s to %s' % (amount, name))
