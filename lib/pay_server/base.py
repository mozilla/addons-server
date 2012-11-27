import datetime
import decimal
from functools import partial
import json
import logging
import urllib


from django_statsd.clients import statsd
import requests

from tower import ugettext as _

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
    # BlueVia APIs
    'prepare_bluevia_pay': ['bluevia', 'prepare-pay', ['post']],
    'verify_bluevia_jwt': ['bluevia', 'verify-jwt', ['post']],
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
}


class Encoder(json.JSONEncoder):

    date_format = '%Y-%m-%d'
    time_format = '%H:%M:%S'

    def default(self, v):
        """Encode some of our basic types in ways solitude understands."""
        if isinstance(v, datetime.datetime):
            return v.strftime("%s %s" % (self.date_format, self.time_format))
        elif isinstance(v, datetime.date):
            return v.strftime(self.date_format)
        elif isinstance(v, datetime.time):
            return v.strftime(self.time_format)
        elif isinstance(v, decimal.Decimal):
            return str(v)
        else:
            return super(Encoder, self).default(v)

general_error = _('Oops, we had an error processing that.')


class Client(object):

    def __init__(self, config=None):
        self.config = self.parse(config)
        self.encoder = None
        self.filter_encoder = urllib.urlencode

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
