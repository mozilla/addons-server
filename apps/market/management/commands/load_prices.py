from optparse import make_option
import pprint

import requests

from django.core.management.base import BaseCommand

from market.models import Price, PriceCurrency


domains = {
    'prod': 'https://marketplace.firefox.com',
    'stage': 'https://marketplace.allizom.org',
    'dev': 'https://marketplace-dev.allizom.org'
}

endpoint = '/api/v1/webpay/prices/'


class Command(BaseCommand):
    help = """
    Load prices and pricecurrencies from the specified marketplace.
    Defaults to prod.
    """
    option_list = BaseCommand.option_list + (
        make_option('--prod',
                    action='store_const',
                    const=domains['prod'],
                    dest='domain',
                    default=domains['prod'],
                    help='Use prod as source of data.'),
        make_option('--stage',
                    action='store_const',
                    const=domains['stage'],
                    dest='domain',
                    help='Use stage as source of data.'),
        make_option('--dev',
                    action='store_const',
                    const=domains['dev'],
                    dest='domain',
                    help='Use use dev as source of data.'),
        make_option('--delete',
                    action='store_true',
                    dest='delete',
                    default=False,
                    help='Start by deleting all prices.'),
        make_option('--noop',
                    action='store_true',
                    dest='noop',
                    default=False,
                    help=('Show data that would be added, '
                          'but do not create objects.')),
    )

    def handle(self, *args, **kw):

        data = requests.get(kw['domain'] + endpoint).json()

        if kw['delete']:
            Price.objects.all().delete()
            PriceCurrency.objects.all().delete()

        if kw['noop']:
            pprint.pprint(data['objects'], indent=2)
        else:
            for p in data['objects']:
                pr = Price.objects.create(name=p['name'].split(' ')[-1],
                                          price=p['price'])
                for pc in p['prices']:
                    pr.pricecurrency_set.create(currency=pc['currency'],
                                                price=pc['price'],
                                                provider=pc['provider'],
                                                method=pc['method'],
                                                region=pc['region'])
