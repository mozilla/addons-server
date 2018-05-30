from django.db import transaction

from market.models import Price


@transaction.commit_on_success
def run():
    print('Renaming tiers')
    for k, tier in enumerate(Price.objects.no_cache().filter(active=True)
                                  .order_by('price')):
        new = 'Tier %s' % k
        print('Renaming %s to %s' % (tier.name, new))
        tier.name = new
        tier.save()
