import datetime
import decimal
from functools import partial
import json
import logging
import urllib

from curling.lib import API
from django_statsd.clients import statsd
import requests

from tower import ugettext_lazy as _

from .errors import lookup

log = logging.getLogger('s.client')


class SolitudeError(Exception):

    def __init__(self, *args, **kwargs):
        self.code = kwargs.pop('code', 0)
        super(SolitudeError, self).__init__(*args, **kwargs)


class SolitudeOffline(SolitudeError):
    pass


class SolitudeTimeout(SolitudeError):
    pass


mapping = {
    'buyer': ['generic', 'buyer', ['get', 'post']],
    'buyer_paypal': ['paypal', 'buyer', ['get', 'post', 'patch', 'delete']],
    'seller': ['generic', 'seller', ['get', 'post']],
    'seller_paypal': ['paypal', 'seller', ['get', 'post', 'patch']],
    'seller_bluevia': ['bluevia', 'seller', ['get', 'post', 'patch']],
    'product': ['generic', 'product', ['get', 'post']],
    # PayPal APIs
    'account_check': ['paypal', 'account-check', ['post']],
    'ipn': ['paypal', 'ipn', ['post']],
    'preapproval': ['paypal', 'preapproval', ['post', 'put', 'delete']],
    'pay': ['paypal', 'pay', ['post']],
    'pay_check': ['paypal', 'pay-check', ['post']],
    'permission_url': ['paypal', 'permission-url', ['post']],
    'permission_token': ['paypal', 'permission-token', ['post']],
    'personal_basic': ['paypal', 'personal-basic', ['post']],
    'personal_advanced': ['paypal', 'personal-advanced', ['post']],
    'refund': ['paypal', 'refund', ['post']],
    # Bango APIs
    'package': ['bango', 'package', ['get', 'post', 'patch']],
    'bank_details': ['bango', 'bank', ['get', 'post']],
    'product_bango': ['bango', 'product', ['get', 'post']],
    'make_premium': ['bango', 'premium', ['post']],
    'make_free': ['bango', 'free', ['post']],
    'update_rating': ['bango', 'rating', ['post']],
}


date_format = '%Y-%m-%d'
time_format = '%H:%M:%S'


class Encoder(json.JSONEncoder):

    ENCODINGS = {
        datetime.datetime:
            lambda v: v.strftime('%s %s' % (date_format, time_format)),
        datetime.date: lambda v: v.strftime(date_format),
        datetime.time: lambda v: v.strftime(time_format),
        decimal.Decimal: str,
    }

    def default(self, v):
        """Encode some of our basic types in ways solitude understands."""
        return self.ENCODINGS.get(type(v), super(Encoder, self).default)(v)


general_error = _('Oops, we had an error processing that.')


class Client(object):

    def __init__(self, config=None):
        self.config = self.parse(config)
        self.api = API(config['server'])
        self.encoder = None
        self.filter_encoder = urllib.urlencode

    def call_uri(self, uri, method='get', data=None):
        """If you were given a URI by Solitude, pass it here and get that
        the value back. Since the URLs are relative, they couldn't simply be
        passed to `call()`. This handles all the prefixing and whatnot.

        """
        uri = uri.lstrip('/')
        return self.call('%s/%s' % (self.config['server'], uri), method, data)

    def _url(self, context, name, pk=None):
        url = '%s/%s/%s/' % (self.config['server'], context, name)
        if pk:
            url = '%s%s/' % (url, pk)
        return url

    def parse(self, config=None):
        config = {
            'server': config.get('server')
            # TODO: add in OAuth stuff.
        }
        return config

    def call(self, url, method_name, data=None):
        log.info('Deprecated, please use curling: %s, %s' % (url, method_name))
        if data and method_name.lower() == 'get':
            raise TypeError('You cannot use data in a GET request. '
                            'Maybe you meant to use filters=...')

        data = (json.dumps(data, cls=self.encoder or Encoder)
                if data else json.dumps({}))
        method = getattr(requests, method_name)

        try:
            with statsd.timer('solitude.call.%s' % method_name):
                result = method(url, data=data,
                                headers={'content-type': 'application/json'},
                                timeout=self.config.get('timeout', 10))
        except requests.ConnectionError:
            log.error('Solitude not accessible')
            raise SolitudeOffline(general_error)
        except requests.Timeout:
            log.error('Solitude timed out, limit %s'
                      % self.config.get('timeout', 10))
            raise SolitudeTimeout(general_error)

        if result.status_code in (200, 201, 202, 204):
            return json.loads(result.text) if result.text else {}
        else:
            log.error('Solitude error with %s: %r' % (url, result.text))
            res = {}
            try:
                res = json.loads(result.text) if result.text else {}
            except:
                # Not a JSON error.
                pass
            code = res.get('error_code', 0)
            raise SolitudeError(lookup(code, res.get('error_data', {})),
                                code=code)

    def upsert(self, method, params, lookup_by):
        """Shortcut function for calling get_<method> and subsequently calling
        post_<method> if there are no results. The values passed to the data
        param of get_<method> are the keys defined in the sequence `lookup_by`.

        """
        lookup_data = dict((k, v) for k, v in params.items() if k in lookup_by)
        existing = self.__getattr__('get_%s' % method)(filters=lookup_data)
        if existing['meta']['total_count']:
            return existing['objects'][0]

        return self.__getattr__('post_%s' % method)(data=params)

    def __getattr__(self, attr):
        try:
            method, action = attr.split('_', 1)
        except:
            raise AttributeError(attr)

        target = mapping.get(action)
        if not target:
            raise AttributeError(attr)

        if method not in target[2]:
            raise AttributeError(attr)

        return partial(self.wrapped, **{'target': target, 'method': method})

    def wrapped(self, target=None, method=None, data=None, pk=None,
                filters=None):
        url = self._url(*target[:2], pk=pk)
        if filters:
            url = '%s?%s' % (url, self.filter_encoder(filters))
        return self.call(url, method, data=data)
