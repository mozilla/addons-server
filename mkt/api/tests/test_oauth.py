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
import time
import urllib
import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import (encode_multipart, Client, FakePayload,
                                BOUNDARY, MULTIPART_CONTENT)

import oauth2 as oauth
from mock import Mock, patch
from nose.tools import eq_
from piston.models import Consumer

from amo.tests import TestCase
from amo.urlresolvers import reverse
from files.models import FileUpload


def _get_args(consumer):
    return dict(
        oauth_consumer_key=consumer.key,
        oauth_nonce=oauth.generate_nonce(),
        oauth_signature_method='HMAC-SHA1',
        oauth_timestamp=int(time.time()),
        oauth_version='1.0',
    )


def get_absolute_url(url):
    url[1]['api_name'] = 'apps'
    rev = reverse(url[0], kwargs=url[1])
    return 'http://%s%s' % ('api', rev)


def data_keys(d):
    # Form keys and values MUST be part of the signature.
    # File keys MUST be part of the signature.
    # But file values MUST NOT be included as part of the signature.
    return dict([k, '' if isinstance(v, file) else v] for k, v in d.items())


class OAuthClient(Client):
    """OauthClient can make magically signed requests."""
    signature_method = oauth.SignatureMethod_HMAC_SHA1()

    def __init__(self, consumer):
        super(OAuthClient, self).__init__(self)
        self.consumer = consumer

    def header(self, method, url):
        req = oauth.Request(method=method, url=url,
                            parameters=_get_args(self.consumer))
        req.sign_request(self.signature_method, self.consumer, None)
        return req.to_header()['Authorization']

    def get(self, url):
        url = get_absolute_url(url)
        return super(OAuthClient, self).get(url,
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('GET', url))

    def delete(self, url):
        url = get_absolute_url(url)
        return super(OAuthClient, self).delete(url,
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('DELETE', url))

    def post(self, url, body=None):
        url = get_absolute_url(url)
        return super(OAuthClient, self).post(url, body=body,
                        content_type='application/json',
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('POST', url))

    def put(self, url, consumer=None, token=None, callback=False,
            verifier=None, data={}, content_type=MULTIPART_CONTENT, **kwargs):
        """
        Send a resource to the server using PUT.
        """
        # TODO: clean this up like the other verbs.
        # If data has come from JSON remove unicode keys.
        data = dict([(str(k), v) for k, v in data.items()])
        url = get_absolute_url(url)
        params = _get_args(consumer)
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

        self.client = OAuthClient(self.accepted_consumer)


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestBaseOAuth(BaseOAuth):
    # Note: these tests are using the validation api to test authentication
    # using oquth. Ideally those tests would be done seperately.

    def setUp(self):
        super(TestBaseOAuth, self).setUp()
        FileUpload.objects.create(uuid='123',
                user=self.accepted_consumer.user.get_profile())
        self.url = ('api_dispatch_detail',
                    {'resource_name': 'validation',
                     'pk': '123'})

    def test_no_auth(self):
        client = Client()
        url = get_absolute_url(self.url)
        eq_(client.get(url).status_code, 401)

    def test_accepted(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_cancelled(self):
        self.client = OAuthClient(self.canceled_consumer)
        eq_(self.client.get(self.url).status_code, 401)

    def test_pending(self):
        client = OAuthClient(self.pending_consumer)
        eq_(client.get(self.url).status_code, 401)

    def test_request_token_fake(self):
        c = Mock()
        c.key = self.accepted_consumer.key
        c.secret = 'mom'
        self.client = OAuthClient(c)
        res = self.client.get(self.url)
        eq_(res.status_code, 401)

    def test_request_no_user(self):
        self.user.delete()
        eq_(self.client.get(self.url).status_code, 401)

    def test_request_no_groups_for_you(self):
        admin = User.objects.get(email='admin@mozilla.com')
        self.accepted_consumer.user = admin
        self.accepted_consumer.save()
        eq_(self.client.get(self.url).status_code, 401)
