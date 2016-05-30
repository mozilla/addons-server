# -*- coding: utf-8 -*-
from olympia.lib.constants import ALL_CURRENCIES

# Source, PayPal docs, PP_AdaptivePayments.PDF
PAYPAL_CURRENCIES = ['AUD', 'BRL', 'CAD', 'CHF', 'CZK', 'DKK', 'EUR', 'GBP',
                     'HKD', 'HUF', 'ILS', 'JPY', 'MXN', 'MYR', 'NOK', 'NZD',
                     'PHP', 'PLN', 'SEK', 'SGD', 'THB', 'TWD', 'USD']
PAYPAL_CURRENCIES = dict((k, ALL_CURRENCIES[k]) for k in PAYPAL_CURRENCIES)

CURRENCY_DEFAULT = 'USD'
