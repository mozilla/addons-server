from datetime import datetime
import json
import urllib
import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import Client, FakePayload

import oauth2 as oauth
from mock import Mock, patch
from nose.tools import eq_
from mkt.api.models import Access, generate

from amo.tests import TestCase
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from files.models import FileUpload
from mkt.api.authentication import errors


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

    def __init__(self, access):
        super(OAuthClient, self).__init__(self)
        self.access = access

    def header(self, method, url):
        if not self.access:
            return None

        parsed = urlparse.urlparse(url)
        args = dict(urlparse.parse_qs(parsed.query))

        req = oauth.Request.from_consumer_and_token(self.access,
            token=None, http_method=method,
            http_url=urlparse.urlunparse(parsed._replace(query='')),
            parameters=args)

        req.sign_request(self.signature_method, self.access, None)
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
            'wsgi.input': FakePayload(data),
            'HTTP_HOST': 'api',
            'HTTP_AUTHORIZATION': self.header('PATCH', url)
        }
        response = self.request(**r)
        return response


class BaseOAuth(TestCase):
    fixtures = ['base/user_2519', 'base/users']

    def setUp(self):
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())

        self.access = Access.objects.create(key='foo', secret=generate(),
                                            user=self.user)
        self.client = OAuthClient(self.access)

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
                user=self.access.user.get_profile())
        self.url = ('api_dispatch_detail',
                    {'resource_name': 'validation',
                     'pk': '123'})

    def test_no_auth(self):
        client = Client()
        url = get_absolute_url(self.url)
        eq_(client.get(url).status_code, 401)

    def test_accepted(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_no_agreement(self):
        self.user.get_profile().update(read_dev_agreement=None)
        res = self.client.get(self.url)
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['terms'])

    def test_request_token_fake(self):
        c = Mock()
        c.key = self.access.key
        c.secret = 'mom'
        self.client = OAuthClient(c)
        res = self.client.get(self.url)
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['headers'])

    def test_request_no_groups_for_you(self):
        admin = User.objects.get(email='admin@mozilla.com')
        self.access.user = admin
        self.access.save()
        res = self.client.get(self.url)
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['roles'])
