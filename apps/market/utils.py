import csv

import commonware.log

from decimal import Decimal
from market.models import Price, PriceCurrency

log = commonware.log.getLogger('z.market')


def update(tiers):
    """
    Updates the prices and price currency objects based on the tiers.

    Tiers should be a list containing a dictionary of currency / value pairs.
    The value of US is required so that we can look up the price tier. If the
    price tier for US isn't found, we skip whole tier. If the currency isn't
    found but the tier is, we create the currency.

    This is intended to be called via a migration or other command.
    """
    output = []
    for row in tiers:
        us = row.get('USD')
        if not us:
            output.append('No USD in row, skipped')
            continue

        try:
            tier = Price.objects.get(price=Decimal(us))
        except Price.DoesNotExist:
            output.append('Tier not found, skipping: %s' % us)
            continue

        for currency, value in row.iteritems():
            if currency == 'USD':
                continue

            try:
                curr = PriceCurrency.objects.get(tier=tier, currency=currency)
            except PriceCurrency.DoesNotExist:
                curr = PriceCurrency(tier=tier, currency=currency)

            curr.price = Decimal(value)
            curr.save()
            output.append('Currency updated: %s, %s, tier %s' %
                          (currency, value, us))

    return output


def update_from_csv(handle):
    reader = csv.reader(handle, delimiter='\t')
    headers = []
    output = []
    for row in reader:
        if not headers:
            headers = row
            continue
        output.append(dict(zip(headers, row)))

    return update(output)
