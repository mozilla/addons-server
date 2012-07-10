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
import urllib
import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import Client

import oauth2 as oauth
from mock import Mock, patch
from nose.tools import eq_
from piston.models import Consumer

from amo.tests import TestCase
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from files.models import FileUpload


def get_absolute_url(url):
    # TODO (andym): make this more standard.
    url[1]['api_name'] = 'apps'
    rev = reverse(url[0], kwargs=url[1])
    res = 'http://%s%s' % ('api', rev)
    if len(url) > 2:
        res = urlparams(res, **url[2])
    return res


class OAuthClient(Client):
    """
    OAuthClient can do all the requests the Django test client,
    but even more. And it can magically sign requests.
    TODO (andym): this could be cleaned up and split out, it's useful.
    """
    signature_method = oauth.SignatureMethod_HMAC_SHA1()

    def __init__(self, consumer):
        super(OAuthClient, self).__init__(self)
        self.consumer = consumer

    def header(self, method, url):
        if not self.consumer:
            return None

        parsed = urlparse.urlparse(url)
        args = dict(urlparse.parse_qs(parsed.query))

        req = oauth.Request.from_consumer_and_token(self.consumer,
            token=None, http_method=method,
            http_url=urlparse.urlunparse(parsed._replace(query='')),
            parameters=args)

        req.sign_request(self.signature_method, self.consumer, None)
        return req.to_header()['Authorization']

    def get(self, url, **kw):
        url = get_absolute_url(url)
        return super(OAuthClient, self).get(url,
                     HTTP_HOST='api',
                     HTTP_AUTHORIZATION=self.header('GET', url),
                     **kw)

    def delete(self, url):
        url = get_absolute_url(url)
        return super(OAuthClient, self).delete(url,
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('DELETE', url))

    def post(self, url, data=''):
        url = get_absolute_url(url)
        return super(OAuthClient, self).post(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('POST', url))

    def put(self, url, data=''):
        url = get_absolute_url(url)
        return super(OAuthClient, self).put(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('PUT', url))

    def patch(self, url, data=''):
        url = get_absolute_url(url)
        parsed = urlparse.urlparse(url)
        r = {
            'CONTENT_LENGTH': len(data),
            'CONTENT_TYPE': 'application/json',
            'PATH_INFO': urllib.unquote(parsed[2]),
            'REQUEST_METHOD': 'PATCH',
            'wsgi.input': data,
            'HTTP_HOST': 'api',
            'HTTP_AUTHORIZATION': self.header('PATCH', url)
        }
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

    def _allowed_verbs(self, url, allowed):
        """
        Will run through all the verbs except the ones specified in allowed
        and ensure that hitting those produces a 405. Otherwise the test will
        fail.
        """
        verbs = ['get', 'post', 'put', 'patch', 'delete']
        for verb in verbs:
            if verb in allowed:
                continue
            res = getattr(self.client, verb)(url)
            assert res.status_code in (401, 405), (
                   '%s: %s not 401 or 405' % (verb.upper(), res.status_code))

    def get_error(self, response):
        return json.loads(response.content)['error_message']


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
