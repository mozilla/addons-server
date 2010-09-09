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
import random
import time
import urlparse
from hashlib import md5

from django.test.client import Client

import oauth2 as oauth
from mock import Mock
from nose.tools import eq_
from test_utils import TestCase
from piston.models import Consumer, Token

from amo.urlresolvers import reverse


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
    return 'http://%s%s' % ('api', reverse(url))


class OAuthClient(Client):
    """OauthClient can make magically signed requests."""
    def get(self, url, consumer=None, token=None, callback=False,
            verifier=None):
        url = get_absolute_url(url)
        req = oauth.Request(method="GET", url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))
        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)
        return super(OAuthClient, self).get(req.to_url(), HTTP_HOST='api',
                                            **req)


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


class TestOauth(TestCase):
    fixtures = ('base/users',)

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
            r = self.client.post(url, d)

            if callback:
                redir = r.get('location', None)
                qs = urlparse.urlsplit(redir).query
                data = urlparse.parse_qs(qs)
                verifier = data['oauth_verifier'][0]
            else:
                eq_(r.status_code, 200)

            piston_token = Token.objects.get()
            assert piston_token.is_approved, "Token not saved."
        else:
            del d['authorize_access']
            r = self.client.post(url, d)
            piston_token = Token.objects.get()
            assert not piston_token.is_approved, "Token saved."

        token = get_access_token(consumer, token, authorize, verifier)

        r = client.get('api.user', consumer, token)

        if authorize:
            data = json.loads(r.content)
            eq_(data['email'], 'admin@mozilla.com')
        else:
            eq_(r.status_code, 401)

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
