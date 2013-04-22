from decimal import Decimal

from django.db import transaction

from market.models import Price


@transaction.commit_on_success
def run():
    print 'Adding in new tiers'
    for tier in ['0.10', '0.25', '0.50', '12.49']:
        exists = Price.uncached.filter(price=Decimal(tier)).exists()
        if exists:
            print 'Tier already exists, skipping: %s' % tier
            continue

        print 'Created tier: %s' % tier
        Price.objects.create(name='Tier 0', price=Decimal(tier),
                             active=True)

    print 'Removing old tiers'
    for tier in ['5.99', '7.99', '8.99', '10.99', '11.99', '12.99', '13.99',
                 '15.99', '16.99', '17.99', '18.99', '20.99', '21.99', '22.99',
                 '23.99', '34.99', '44.99']:
        try:
            price = Price.uncached.get(price=Decimal(tier))
            price.active = False
            price.save()
            print 'Deactivating tier: %s' % tier
        except Price.DoesNotExist:
            print 'Tier does not exist, skipping: %s' % tier

    print 'Renaming tiers'
    for k, tier in enumerate(Price.uncached.filter(active=True)
                                  .order_by('price')):
        new = 'Tier %s' % k
        print 'Renaming %s to %s' % (tier.name, new)
        tier.name = new
        tier.save()
