"""
Verifies basic OAUTH functionality in AMO.

Sample request_token query:
    /en-US/firefox/oauth/request_token/?
        oauth_consumer_key=GYKEp7m5fJpj9j8Vjz&
        oauth_nonce=A7A79B47-B571-4D70-AA6C-592A0555E94B&
        oauth_signature_method=HMAC-SHA1&
        oauth_timestamp=1282950712&
        oauth_version=1.0

With headers:

    Authorization: OAuth realm="",
    oauth_consumer_key="GYKEp7m5fJpj9j8Vjz",
    oauth_signature_method="HMAC-SHA1",
    oauth_signature="JBCA4ah%2FOQC0lLWV8aChGAC+15s%3D",
    oauth_timestamp="1282950995",
    oauth_nonce="1008F707-37E6-4ABF-8322-C6B658771D88",
    oauth_version="1.0"
"""
import json
import os
import time
import urlparse

from django.conf import settings
from django.test.client import Client

import oauth2 as oauth
from mock import Mock
from nose.tools import eq_
from test_utils import TestCase
from piston.models import Consumer, Token

from amo.urlresolvers import reverse
from addons.models import Addon
from translations.models import Translation


def _get_args(consumer, token=None, callback=False, verifier=None):
    d = dict(
            oauth_consumer_key=consumer.key,
            oauth_nonce=oauth.generate_nonce(),
            oauth_signature_method='HMAC-SHA1',
            oauth_timestamp=int(time.time()),
            oauth_version='1.0',
            )

    if token:
        d['oauth_token'] = token

    if callback:
        d['oauth_callback'] = 'http://testserver/foo'

    if verifier:
        d['oauth_verifier'] = verifier

    return d


def get_absolute_url(url):
    if isinstance(url, tuple):
        url = reverse(url[0], args=url[1:])
    else:
        url = reverse(url)

    return 'http://%s%s' % ('api', url)


class OAuthClient(Client):
    """OauthClient can make magically signed requests."""
    def get(self, url, consumer=None, token=None, callback=False,
            verifier=None):
        url = get_absolute_url(url)
        req = oauth.Request(method='GET', url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))
        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)
        return super(OAuthClient, self).get(req.to_url(), HTTP_HOST='api',
                                            **req)

    def post(self, url, consumer=None, token=None, callback=False,
             verifier=None, data={}):
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        req = oauth.Request(method='POST', url=url, parameters=params)
        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)
        return super(OAuthClient, self).post(req.to_url(), HTTP_HOST='api',
                                             data=data, **req)

    def put(self, url, consumer=None, token=None, callback=False,
            verifier=None, data={}):
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        params.update(data)
        req = oauth.Request(method='PUT', url=url, parameters=params)
        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)
        return super(OAuthClient, self).put(req.to_url(), HTTP_HOST='api',
                                            data=req, **req)
client = OAuthClient()
token_keys = ('oauth_token_secret', 'oauth_token',)


def get_token_from_response(response):
    data = urlparse.parse_qs(response.content)

    for key in token_keys:
        assert key in data.keys(), '%s not in %s' % (key, data.keys())

    return oauth.Token(key=data['oauth_token'][0],
                       secret=data['oauth_token_secret'][0])


def get_request_token(consumer, callback=False):
    r = client.get('oauth.request_token', consumer, callback=callback)
    return get_token_from_response(r)


def get_access_token(consumer, token, authorize=True, verifier=None):
    r = client.get('oauth.access_token', consumer, token, verifier=verifier)

    if authorize:
        return get_token_from_response(r)
    else:
        eq_(r.status_code, 401)


class BaseOauth(TestCase):
    fixtures = ('base/users', 'base/appversion', 'base/platforms')

    def setUp(self):
        consumers = []
        for status in ('accepted', 'pending', 'canceled', ):
            c = Consumer(name='a', status=status)
            c.generate_random_codes()
            c.save()
            consumers.append(c)
        self.accepted_consumer = consumers[0]
        self.pending_consumer = consumers[1]
        self.canceled_consumer = consumers[2]

    def _login(self):
        self.client.login(username='admin@mozilla.com', password='password')

    def _oauth_flow(self, consumer, authorize=True, callback=False):
        """
        1. Get Request Token.
        2. Request Authorization.
        3. Get Access Token.
        4. Get to protected resource.
        """
        token = get_request_token(consumer, callback)

        self._login()
        url = (reverse('oauth.authorize') + '?oauth_token=' + token.key)
        r = self.client.get(url)
        eq_(r.status_code, 200)

        d = dict(authorize_access='on', oauth_token=token.key)

        if callback:
            d['oauth_callback'] = 'http://testserver/foo'

        verifier = None

        if authorize:
            r = self.client.post(url, d,)

            if callback:
                redir = r.get('location', None)
                qs = urlparse.urlsplit(redir).query
                data = urlparse.parse_qs(qs)
                verifier = data['oauth_verifier'][0]
            else:
                eq_(r.status_code, 200)

            piston_token = Token.objects.get(key=token.key)
            assert piston_token.is_approved, "Token not saved."
        else:
            del d['authorize_access']
            r = self.client.post(url, d)
            piston_token = Token.objects.get()
            assert not piston_token.is_approved, "Token saved."

        self.token = get_access_token(consumer, token, authorize, verifier)

        r = client.get('api.user', consumer, self.token)

        if authorize:
            data = json.loads(r.content)
            eq_(data['email'], 'admin@mozilla.com')
        else:
            eq_(r.status_code, 401)


class TestBasicOauth(BaseOauth):

    def test_accepted(self):
        self._oauth_flow(self.accepted_consumer)

    def test_accepted_callback(self):
        """Same as above, just uses a callback."""
        self._oauth_flow(self.accepted_consumer, callback=True)

    def test_unauthorized(self):
        self._oauth_flow(self.accepted_consumer, authorize=False)

    def test_request_token_pending(self):
        get_request_token(self.pending_consumer)

    def test_request_token_cancelled(self):
        get_request_token(self.canceled_consumer)

    def test_request_token_fake(self):
        """Try with a phony consumer key"""
        c = Mock()
        c.key = 'yer'
        c.secret = 'mom'
        r = client.get('oauth.request_token', c)
        eq_(r.content, 'Invalid consumer.')


class TestAddon(BaseOauth):

    def setUp(self):
        super(TestAddon, self).setUp()
        consumer = self.accepted_consumer
        self._oauth_flow(consumer)
        path = 'apps/api/fixtures/api/helloworld.xpi'
        xpi = os.path.join(settings.ROOT, path)
        f = open(xpi)

        self.create_data = dict(
                license_type='other',
                license_text='This is FREE!',
                platform='mac',
                xpi=f,
                )

    def make_create_request(self, data):
        return client.post('api.addons', self.accepted_consumer, self.token,
                           data=data)

    def test_create(self):
        # License (req'd): MIT, GPLv2, GPLv3, LGPLv2.1, LGPLv3, MIT, BSD, Other
        # Custom License (if other, req'd)
        # XPI file... (req'd)
        # Platform (All by default): 'mac', 'all', 'bsd', 'linux', 'solaris',
        #   'windows'

        r = self.make_create_request(self.create_data)

        eq_(r.status_code, 200, r.content)

        data = json.loads(r.content)
        id = data['id']
        name = data['name']
        eq_(name, 'XUL School Hello World')
        assert Addon.objects.get(pk=id)

    def test_create_nolicense(self):
        data = {}

        r = self.make_create_request(data)
        eq_(r.status_code, 400, r.content)
        eq_(r.content, 'Bad Request: '
            'Invalid license data provided: License text missing.')

    def test_update(self):
        # create an addon
        r = self.make_create_request(self.create_data)
        data = json.loads(r.content)
        id = data['id']

        # icon, homepage, support email,
        # support website, get satisfaction, gs_optional field, allow source
        # viewing, set flags
        data = dict(
                name='fu',
                default_locale='fr',
                homepage='mozilla.com',
                support_email='go@away.com',
                support_url='http://google.com/',
                description='it sucks',
                summary='sucks',
                developer_comments='i made it suck hard.',
                eula='love it',
                privacy_policy='aybabtu',
                the_reason='for shits',
                the_future='is gone',
                view_source=1,
                prerelease=1,
                binary=1,
                site_specific=1,
                get_satisfaction_company='yermom',
                get_satisfaction_product='yer face',
        )

        r = client.put(('api.addon', id), self.accepted_consumer, self.token,
                       data=data)
        eq_(r.status_code, 200, r.content)

        a = Addon.objects.get(pk=id)
        for field, expected in data.iteritems():
            value = getattr(a, field)
            if isinstance(value, Translation):
                value = unicode(value)

            eq_(value, expected,
                "'%s' didn't match: got '%s' instead of '%s'"
                % (field, getattr(a, field), expected))
