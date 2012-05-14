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
import time
import urllib
import urlparse

from django.contrib.auth.models import User
from django.test.client import (encode_multipart, Client, FakePayload,
                                BOUNDARY, MULTIPART_CONTENT)

import oauth2 as oauth
from mock import Mock, patch
from nose.tools import eq_
from piston.models import Consumer

from amo.tests import TestCase
from amo.urlresolvers import reverse


def _get_args(consumer, token=None, callback=False, verifier=None):
    d = dict(
            oauth_consumer_key=consumer.key,
            oauth_nonce=oauth.generate_nonce(),
            oauth_signature_method='HMAC-SHA1',
            oauth_timestamp=int(time.time()),
            oauth_version='1.0',
            )

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


def data_keys(d):
    # Form keys and values MUST be part of the signature.
    # File keys MUST be part of the signature.
    # But file values MUST NOT be included as part of the signature.
    return dict([k, '' if isinstance(v, file) else v] for k, v in d.items())


class OAuthClient(Client):
    """OauthClient can make magically signed requests."""
    signature_method = oauth.SignatureMethod_HMAC_SHA1()

    def get(self, url, consumer=None, token=None, callback=False,
            verifier=None, params=None):
        url = get_absolute_url(url)
        if params:
            url = '%s?%s' % (url, urllib.urlencode(params))
        req = oauth.Request(method='GET', url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))
        req.sign_request(self.signature_method, consumer, token)
        return super(OAuthClient, self).get(req.to_url(), HTTP_HOST='api',
                                            **req)

    def delete(self, url, consumer=None, token=None, callback=False,
               verifier=None):
        url = get_absolute_url(url)
        req = oauth.Request(method='DELETE', url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))

        req.sign_request(self.signature_method, consumer, token)
        return super(OAuthClient, self).delete(req.to_url(), HTTP_HOST='api',
                                               **req)

    def post(self, url, consumer=None, token=None, callback=False,
             verifier=None, data={}):
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        params.update(data_keys(data))
        req = oauth.Request(method='POST', url=url, parameters=params)
        req.sign_request(self.signature_method, consumer, token)
        return super(OAuthClient, self).post(req.to_url(), HTTP_HOST='api',
                                             data=data,
                                             headers=req.to_header())

    def put(self, url, consumer=None, token=None, callback=False,
            verifier=None, data={}, content_type=MULTIPART_CONTENT, **kwargs):
        """
        Send a resource to the server using PUT.
        """
        # If data has come from JSON remove unicode keys.
        data = dict([(str(k), v) for k, v in data.items()])
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        params.update(data_keys(data))

        req = oauth.Request(method='PUT', url=url, parameters=params)
        req.sign_request(self.signature_method, consumer, token)
        post_data = encode_multipart(BOUNDARY, data)

        parsed = urlparse.urlparse(url)
        query_string = urllib.urlencode(req, doseq=True)
        r = {
            'CONTENT_LENGTH': len(post_data),
            'CONTENT_TYPE':   content_type,
            'PATH_INFO':      urllib.unquote(parsed[2]),
            'QUERY_STRING':   query_string,
            'REQUEST_METHOD': 'PUT',
            'wsgi.input':     FakePayload(post_data),
            'HTTP_HOST':      'api',
        }
        r.update(req)

        response = self.request(**r)
        return response


class BaseOAuth(TestCase):
    fixtures = ['base/user_2519', 'base/users']

    def setUp(self):
        self.user = User.objects.get(pk=2519)

        for status in ('accepted', 'pending', 'canceled', ):
            c = Consumer(name='a', status=status, user=self.user)
            c.generate_random_codes()
            c.save()
            setattr(self, '%s_consumer' % status, c)

        self.client = OAuthClient()


class TestBaseOAuth(BaseOAuth):

    def setUp(self):
        super(TestBaseOAuth, self).setUp()
        self.url = 'api.validation'

    def test_accepted(self):
        eq_(self.client.get(self.url, self.accepted_consumer).status_code,
            404)

    def test_cancelled(self):
        eq_(self.client.get(self.url, self.canceled_consumer).status_code,
            401)

    def test_pending(self):
        eq_(self.client.get(self.url, self.pending_consumer).status_code,
            401)

    @patch('mkt.api.handlers.ValidationHandler.read')
    def test_internal_error(self, read):
        read.side_effect = ZeroDivisionError()
        res = self.client.get(self.url, self.accepted_consumer)
        eq_(res.status_code, 500)
        eq_(json.loads(res.content)['error'], 'Internal Error')

    def test_request_token_fake(self):
        c = Mock()
        c.key = self.accepted_consumer.key
        c.secret = 'mom'
        res = self.client.get(self.url, c)
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['error'], 'Invalid OAuthToken.')

    def test_request_no_user(self):
        self.user.delete()
        eq_(self.client.get(self.url, self.accepted_consumer).status_code,
            401)

    def test_request_no_groups_for_you(self):
        admin = User.objects.get(email='admin@mozilla.com')
        self.accepted_consumer.user = admin
        self.accepted_consumer.save()
        eq_(self.client.get(self.url, self.accepted_consumer).status_code,
            401)
