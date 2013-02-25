from datetime import datetime
from functools import partial
import json
import urllib
import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import Client, FakePayload

import oauth2
from mock import patch
from nose.tools import eq_
from test_utils import RequestFactory

from amo.tests import TestCase
from amo.helpers import urlparams
from amo.urlresolvers import reverse

from mkt.api.base import CORSResource
from mkt.api.models import Access, generate
from mkt.site.fixtures import fixture


def get_absolute_url(url, api_name='apps'):
    # TODO (andym): make this more standard.
    url[1]['api_name'] = api_name
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
    signature_method = oauth2.SignatureMethod_HMAC_SHA1()

    def __init__(self, access, api_name='apps'):
        super(OAuthClient, self).__init__(self)
        self.access = access
        self.get_absolute_url = partial(get_absolute_url,
                                        api_name=api_name)

    def header(self, method, url, data=None, **kw):
        if not self.access:
            return None

        parsed = urlparse.urlparse(url)
        args = dict(urlparse.parse_qs(parsed.query))
        if data and isinstance(data, dict):
            args.update(data)

        req = oauth2.Request.from_consumer_and_token(self.access,
            token=None, http_method=method,
            http_url=urlparse.urlunparse(parsed._replace(query='')),
            parameters=args)

        req.sign_request(self.signature_method, self.access, None)
        return req.to_header()['Authorization']

    def get(self, url, **kw):
        url = self.get_absolute_url(url)
        return super(OAuthClient, self).get(url,
                     HTTP_HOST='api',
                     HTTP_AUTHORIZATION=self.header('GET', url, **kw),
                     **kw)

    def delete(self, url, **kw):
        url = self.get_absolute_url(url)
        return super(OAuthClient, self).delete(url,
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('DELETE', url, **kw),
                        **kw)

    def post(self, url, data=''):
        url = self.get_absolute_url(url)
        return super(OAuthClient, self).post(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('POST', url, data=data))

    def put(self, url, data=''):
        url = self.get_absolute_url(url)
        return super(OAuthClient, self).put(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='api',
                        HTTP_AUTHORIZATION=self.header('PUT', url, data=data))

    def patch(self, url, data=''):
        url = self.get_absolute_url(url)
        parsed = urlparse.urlparse(url)
        r = {
            'CONTENT_LENGTH': len(data),
            'CONTENT_TYPE': 'application/json',
            'PATH_INFO': urllib.unquote(parsed[2]),
            'REQUEST_METHOD': 'PATCH',
            'wsgi.input': FakePayload(data),
            'HTTP_HOST': 'api',
            'HTTP_AUTHORIZATION': self.header('PATCH', url, data=data)
        }
        response = self.request(**r)
        return response


class BaseOAuth(TestCase):
    fixtures = fixture('user_2519', 'group_admin', 'group_editor',
                       'group_support')

    def setUp(self, api_name='apps'):
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())

        self.access = Access.objects.create(key='foo', secret=generate(),
                                            user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)

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


class Resource(CORSResource):

    class Meta:
        list_allowed_method = ['get']


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestCORS(BaseOAuth):

    def setUp(self):
        self.resource = Resource()

    def test_cors(self):
        req = RequestFactory().get('/')
        self.resource.method_check(req, allowed=['get'])
        eq_(req.CORS, ['get'])
