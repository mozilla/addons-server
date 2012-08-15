import calendar
from optparse import make_option
import time
from urllib import urlencode

from django.core.management.base import BaseCommand

import jwt
import requests


class Command(BaseCommand):
    help = 'Simulate a BlueVia postback to mark a payment as complete.'
    option_list = BaseCommand.option_list + (
        make_option('--trans-id', action='store',
                    help='BlueVia transaction ID', default='1234'),
        make_option('--secret', action='store',
                    help='Marketplace secret for signature verification'),
        make_option('--contrib', action='store',
                    help='Contribution UUID'),
        make_option('--addon', action='store',
                    help='ID of addon that was purchased'),
        make_option('--url', action='store',
                    help='Postback URL. Default: %default',
                    default='http://localhost:8001/services/bluevia/postback'),
    )

    def handle(self, *args, **options):
        assert 'contrib' in options, 'require --contrib'
        assert 'addon' in options, 'require --addon'
        issued_at = calendar.timegm(time.gmtime())
        prod_data = urlencode({'contrib_uuid': options['contrib'],
                               'addon_id': options['addon']})
        purchase = {'iss': 'tu.com',
                    'aud': 'marketplace.mozilla.org',
                    'typ': 'tu.com/payments/inapp/v1',
                    'iat': issued_at,
                    'exp': issued_at + 3600,  # expires in 1 hour
                    'request': {
                        'name': 'Simulated Product',
                        'description': 'Simulated Product Description',
                        'price': '0.99',
                        'currencyCode': 'USD',
                        'productData': prod_data},
                    'response': {
                        'transactionID': options['trans_id']
                    }}
        purchase_jwt = jwt.encode(purchase, options['secret'])
        print 'posting JWT to %s' % options['url']
        res = requests.post(options['url'], purchase_jwt, timeout=5)
        res.raise_for_status()
        print 'OK'
