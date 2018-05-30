from decimal import Decimal

from django.db import transaction

from market.models import Price


@transaction.commit_on_success
def run():
    print('Adding in new tiers')
    for tier in ['0.10', '0.25', '0.50', '12.49']:
        exists = Price.objects.no_cache().filter(price=Decimal(tier)).exists()
        if exists:
            print('Tier already exists, skipping: %s' % tier)
            continue

        print('Created tier: %s' % tier)
        Price.objects.create(name='Tier 0', price=Decimal(tier),
                             active=True)
