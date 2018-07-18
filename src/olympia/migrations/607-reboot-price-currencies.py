from django.db import models

from market.models import Price

from olympia import amo


tiers = {
    '0.00': {
        'CO': {'currency': 'COP', 'price': '0.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '0.00', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '0.00',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '0.00', 'region': 2},
        'VE': {'currency': 'USD', 'price': '0.00', 'region': 10},
    },
    '0.10': {
        'CO': {'currency': 'COP', 'price': '210.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '0.10', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '0.49',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '0.10', 'region': 2},
        'VE': {'currency': 'USD', 'price': '0.10', 'region': 10},
    },
    '0.25': {
        'CO': {'currency': 'COP', 'price': '520.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '0.25', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '0.99',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '0.25', 'region': 2},
        'VE': {'currency': 'USD', 'price': '0.25', 'region': 10},
    },
    '0.50': {
        'CO': {'currency': 'COP', 'price': '1050.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '0.45', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '1.99',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '0.50', 'region': 2},
        'VE': {'currency': 'USD', 'price': '0.50', 'region': 10},
    },
    '0.99': {
        'CO': {'currency': 'COP', 'price': '2060.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '0.89', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '3.99',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '0.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '0.99', 'region': 10},
    },
    '1.99': {
        'CO': {'currency': 'COP', 'price': '4150.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '1.89', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '7.69',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '1.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '1.99', 'region': 10},
    },
    '12.49': {
        'CO': {'currency': 'COP', 'price': '26070.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '11.59', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '48.49',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '12.49', 'region': 2},
        'VE': {'currency': 'USD', 'price': '12.49', 'region': 10},
    },
    '14.99': {
        'ES': {'currency': 'EUR', 'price': '14.19', 'region': 8},
        'US': {'currency': 'USD', 'price': '14.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '14.99', 'region': 10},
    },
    '19.99': {
        'ES': {'currency': 'EUR', 'price': '18.99', 'region': 8},
        'US': {'currency': 'USD', 'price': '19.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '19.99', 'region': 10},
    },
    '2.99': {
        'CO': {'currency': 'COP', 'price': '6240.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '2.79', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '11.59',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '2.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '2.99', 'region': 10},
    },
    '24.99': {
        'ES': {'currency': 'EUR', 'price': '23.59', 'region': 8},
        'US': {'currency': 'USD', 'price': '24.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '24.99', 'region': 10},
    },
    '29.99': {
        'CO': {'currency': 'COP', 'price': '62580.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '28.39', 'region': 8},
        'US': {'currency': 'USD', 'price': '29.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '29.99', 'region': 10},
    },
    '3.99': {
        'CO': {'currency': 'COP', 'price': '8320.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '3.79', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '15.49',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '3.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '3.99', 'region': 10},
    },
    '39.99': {
        'CO': {'currency': 'COP', 'price': '83460.00', 'region': 9},
        'US': {'currency': 'USD', 'price': '39.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '39.99', 'region': 10},
    },
    '4.99': {
        'CO': {'currency': 'COP', 'price': '10420.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '4.69', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '19.49',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '4.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '4.99', 'region': 10},
    },
    '49.99': {
        'CO': {'currency': 'COP', 'price': '104320.00', 'region': 9},
        'US': {'currency': 'USD', 'price': '49.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '49.99', 'region': 10},
    },
    '6.99': {
        'CO': {'currency': 'COP', 'price': '14600.00', 'region': 9},
        'ES': {'currency': 'EUR', 'price': '6.59', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '26.99',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '6.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '6.99', 'region': 10},
    },
    '9.99': {
        'CO': {
            'currency': 'COP',
            'methods': [],
            'price': '20840.00',
            'region': 9,
        },
        'ES': {'currency': 'EUR', 'price': '9.49', 'region': 8},
        'PL': {
            'currency': 'PLN',
            'operator': 1,
            'price': '38.79',
            'region': 11,
        },
        'US': {'currency': 'USD', 'price': '9.99', 'region': 2},
        'VE': {'currency': 'USD', 'price': '9.99', 'region': 10},
    },
}


# This is because method gets added on to the model later.
class FrozenPriceCurrency(amo.models.ModelBase):
    carrier = models.IntegerField()
    currency = models.CharField(max_length=10)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    provider = models.IntegerField()
    region = models.IntegerField(default=1)
    tier = models.ForeignKey(Price)

    class Meta:
        db_table = 'price_currency'


def run():
    FrozenPriceCurrency.objects.no_cache().all().delete()
    for k in sorted(tiers.keys()):
        v = tiers[k]
        try:
            tier = Price.objects.filter(price=k).no_transforms()[0]
        except IndexError:
            print('Tier does not exist: {0}'.format(k))
            continue

        for country, values in v.items():
            FrozenPriceCurrency.objects.create(
                tier=tier,
                carrier=None,
                provider=1,
                price=values['price'],
                region=values['region'],
                currency=values['currency'],
            )
            print('Creating: {0}, {1}'.format(k, country))
