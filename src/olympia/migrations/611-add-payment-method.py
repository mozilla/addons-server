from constants.payments import PAYMENT_METHOD_CARD, PAYMENT_METHOD_OPERATOR
from market.models import Price, PriceCurrency
from mkt.regions import SPAIN, PL, CO, VE


tiers = {
    '0.10': {SPAIN.id: {'method': PAYMENT_METHOD_OPERATOR},
             PL.id: {'method': PAYMENT_METHOD_OPERATOR},
             VE.id: {'method': PAYMENT_METHOD_CARD}},
    '0.25': {SPAIN.id: {'method': PAYMENT_METHOD_OPERATOR},
             PL.id: {'method': PAYMENT_METHOD_OPERATOR},
             VE.id: {'method': PAYMENT_METHOD_CARD}},
    '0.50': {SPAIN.id: {'method': PAYMENT_METHOD_OPERATOR},
             PL.id: {'method': PAYMENT_METHOD_OPERATOR},
             VE.id: {'method': PAYMENT_METHOD_CARD}},
    '0.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '1.99': {CO.id: {'method': PAYMENT_METHOD_CARD},
             VE.id: {'method': PAYMENT_METHOD_CARD}},
    '2.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '3.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '4.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '6.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '9.99': {VE.id: {'method': PAYMENT_METHOD_CARD},
             CO.id: {'method': PAYMENT_METHOD_CARD}},
    '12.49': {VE.id: {'method': PAYMENT_METHOD_CARD},
              CO.id: {'method': PAYMENT_METHOD_CARD}},
    '14.99': {PL.id: {'method': PAYMENT_METHOD_CARD},
              CO.id: {'method': PAYMENT_METHOD_CARD},
              VE.id: {'method': PAYMENT_METHOD_CARD}},
    '19.99': {PL.id: {'method': PAYMENT_METHOD_CARD},
              CO.id: {'method': PAYMENT_METHOD_CARD},
              VE.id: {'method': PAYMENT_METHOD_CARD}},
    '24.99': {PL.id: {'method': PAYMENT_METHOD_CARD},
              CO.id: {'method': PAYMENT_METHOD_CARD},
              VE.id: {'method': PAYMENT_METHOD_CARD}},
    '29.99': {PL.id: {'method': PAYMENT_METHOD_CARD},
              CO.id: {'method': PAYMENT_METHOD_CARD},
              VE.id: {'method': PAYMENT_METHOD_CARD}},
    '39.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
    '49.99': {VE.id: {'method': PAYMENT_METHOD_CARD}},
}


def run():
    for k in sorted(tiers.keys()):
        v = tiers[k]
        try:
            tier = Price.objects.get(price=k)
        except Price.DoesNotExist:
            print 'Tier does not exist: {0}'.format(k)
            continue

        for region, values in v.items():
            try:
                currency = PriceCurrency.objects.get(tier=tier, region=region)
            except PriceCurrency.DoesNotExist:
                print 'Region does not exist: {0}'.format(region)
                continue

            currency.method = values['method']
            currency.save()
            print 'Updating: {0}, {1}, {2}'.format(k, region, values['method'])
