from datetime import datetime
from functools import partial
import json
import urllib
import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import Client, FakePayload

from nose.tools import eq_
from oauthlib import oauth1
from pyquery import PyQuery as pq
from test_utils import RequestFactory

from amo.tests import TestCase
from amo.helpers import urlparams
from amo.urlresolvers import reverse

from mkt.api import authentication
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.models import Access, Token, generate, REQUEST_TOKEN, ACCESS_TOKEN
from mkt.site.fixtures import fixture


def get_absolute_url(url, api_name='apps', absolute=True):
    # Gets an absolute url, except where you don't want that.
    url[1]['api_name'] = api_name
    res = reverse(url[0], kwargs=url[1])
    if absolute:
        res = '%s%s' % (settings.SITE_URL, res)
    if len(url) > 2:
        res = urlparams(res, **url[2])
    return res


class OAuthClient(Client):
    """
    OAuthClient can do all the requests the Django test client,
    but even more. And it can magically sign requests.
    TODO (andym): this could be cleaned up and split out, it's useful.
    """
    signature_method = oauth1.SIGNATURE_HMAC

    def __init__(self, access, api_name='apps'):
        super(OAuthClient, self).__init__(self)
        self.access = access
        self.get_absolute_url = partial(get_absolute_url,
                                        api_name=api_name)

    def sign(self, method, url):
        if not self.access:
            return url, {}, ''
        cl = oauth1.Client(self.access.key,
                           client_secret=self.access.secret,
                           signature_method=self.signature_method)
        return cl.sign(url, http_method=method)

    def get(self, url, data={}, **kw):
        if len(url) > 2 and data:
            raise RuntimeError('Query string specified both in urlspec and as '
                               'data arg. Pick one or the other.')
        urlstring = get_absolute_url(url)
        if data:
            urlstring = '?'.join([urlstring,
                                  urllib.urlencode(data, doseq=True)])
        url, headers, _ = self.sign('GET', urlstring)
        return super(OAuthClient, self).get(
            url, HTTP_HOST='testserver',
            HTTP_AUTHORIZATION=headers.get('Authorization', ''),
            **kw)

    def delete(self, url, **kw):
        url, headers, _ = self.sign('DELETE', self.get_absolute_url(url))
        return super(OAuthClient, self).delete(url,
                        HTTP_HOST='testserver',
                        HTTP_AUTHORIZATION=headers.get('Authorization', ''),
                        **kw)

    def post(self, url, data='', **kw):
        url, headers, _ = self.sign('POST', self.get_absolute_url(url))
        return super(OAuthClient, self).post(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='testserver',
                        HTTP_AUTHORIZATION=headers.get('Authorization', ''),
                        **kw)

    def put(self, url, data='', **kw):
        url, headers, body = self.sign('PUT', self.get_absolute_url(url))
        return super(OAuthClient, self).put(url, data=data,
                        content_type='application/json',
                        HTTP_HOST='testserver',
                        HTTP_AUTHORIZATION=headers.get('Authorization', ''),
                        **kw)

    def patch(self, url, data='', **kw):
        url, headers, body = self.sign('PATCH', self.get_absolute_url(url))
        parsed = urlparse.urlparse(url)
        kw.update({
            'CONTENT_LENGTH': len(data),
            'CONTENT_TYPE': 'application/json',
            'PATH_INFO': urllib.unquote(parsed[2]),
            'REQUEST_METHOD': 'PATCH',
            'wsgi.input': FakePayload(data),
            'HTTP_HOST': 'testserver',
            'HTTP_AUTHORIZATION': headers.get('Authorization', '')
        })
        response = self.request(**kw)
        return response


class BaseOAuth(TestCase):
    fixtures = fixture('user_2519', 'group_admin', 'group_editor',
                       'group_support')

    def setUp(self, api_name='apps'):
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.access = Access.objects.create(key='oauthClientKeyForTests',
                                            secret=generate(),
                                            user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.anon = OAuthClient(None, api_name=api_name)

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


class Resource(CORSResource, MarketplaceResource):

    class Meta:
        list_allowed_method = ['get']


class TestCORS(BaseOAuth):

    def setUp(self):
        self.resource = Resource()

    def test_cors(self):
        req = RequestFactory().get('/')
        self.resource.method_check(req, allowed=['get'])
        eq_(req.CORS, ['get'])


class Test3LeggedOAuthFlow(TestCase):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self, api_name='apps'):
        self.user = User.objects.get(pk=2519)
        self.user2 = User.objects.get(pk=999)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.app_name = 'Mkt Test App'
        self.redirect_uri = 'https://example.com/redirect_target'
        self.access = Access.objects.create(key='oauthClientKeyForTests',
                                            secret=generate(),
                                            user=self.user,
                                            redirect_uri=self.redirect_uri,
                                            app_name=self.app_name)

    def _oauth_request_info(self, url, **kw):
        oa = oauth1.Client(signature_method=oauth1.SIGNATURE_HMAC, **kw)
        url, headers, _ = oa.sign(url, http_method='GET')
        return url, headers['Authorization']

    def test_use_access_token(self):
        url = get_absolute_url(('api_dispatch_list', {'resource_name': 'app'}))
        t = Token.generate_new(ACCESS_TOKEN, creds=self.access,
                               user=self.user2)
        url, auth_header = self._oauth_request_info(
            url, client_key=self.access.key, client_secret=self.access.secret,
            resource_owner_key=t.key, resource_owner_secret=t.secret)
        auth = authentication.OAuthAuthentication()
        req = RequestFactory().get(
            url, HTTP_HOST='testserver',
            HTTP_AUTHORIZATION=auth_header)
        assert auth.is_authenticated(req)
        eq_(req.user, self.user2)

    def test_bad_access_token(self):
        url = get_absolute_url(('api_dispatch_list', {'resource_name': 'app'}))
        Token.generate_new(ACCESS_TOKEN, creds=self.access, user=self.user2)
        url, auth_header = self._oauth_request_info(
            url, client_key=self.access.key,
            client_secret=self.access.secret, resource_owner_key=generate(),
            resource_owner_secret=generate())
        auth = authentication.OAuthAuthentication()
        req = RequestFactory().get(
            url, HTTP_HOST='testserver',
            HTTP_AUTHORIZATION=auth_header)
        eq_(auth.is_authenticated(req).status_code, 401)

    def test_get_authorize_page(self):
        t = Token.generate_new(REQUEST_TOKEN, self.access)
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get('/oauth/authorize/', data={'oauth_token': t.key})
        eq_(res.status_code, 200)
        page = pq(res.content)
        eq_(page('input[name=oauth_token]').attr('value'), t.key)

    def test_get_authorize_page_bad_token(self):
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get('/oauth/authorize/',
                              data={'oauth_token': 'bad_token_value'})
        eq_(res.status_code, 401)

    def test_post_authorize_page(self):
        t = Token.generate_new(REQUEST_TOKEN, self.access)
        full_redirect = (
            self.redirect_uri + '?oauth_token=%s&oauth_verifier=%s'
            % (t.key, t.verifier))
        self.client.login(username='regular@mozilla.com', password='password')
        url = reverse('mkt.developers.oauth_authorize')
        res = self.client.post(url, data={'oauth_token': t.key, 'grant': ''})
        eq_(res.status_code, 302)
        eq_(res.get('location'), full_redirect)
        eq_(Token.objects.get(pk=t.pk).user.pk, 999)

    def test_access_request(self):
        t = Token.generate_new(REQUEST_TOKEN, self.access)
        url = settings.SITE_URL + reverse(
            'mkt.developers.oauth_access_request')
        url, auth_header = self._oauth_request_info(
            url, client_key=self.access.key, client_secret=self.access.secret,
            resource_owner_key=t.key, resource_owner_secret=t.secret,
            verifier=t.verifier, callback_uri=self.access.redirect_uri)
        res = self.client.get(url, HTTP_HOST='testserver',
                              HTTP_AUTHORIZATION=auth_header)
        eq_(res.status_code, 200)
        data = dict(urlparse.parse_qsl(res.content))
        assert Token.objects.filter(
            token_type=ACCESS_TOKEN,
            key=data['oauth_token'],
            secret=data['oauth_token_secret'],
            user=t.user,
            creds=self.access).exists()
        assert not Token.objects.filter(
            token_type=REQUEST_TOKEN,
            key=t.key).exists()

    def test_bad_access_request(self):
        t = Token.generate_new(REQUEST_TOKEN, self.access)
        url = settings.SITE_URL + reverse(
            'mkt.developers.oauth_access_request')
        url, auth_header = self._oauth_request_info(
            url, client_key=t.key, client_secret=t.secret,
            resource_owner_key=generate(), resource_owner_secret=generate(),
            verifier=generate(), callback_uri=self.access.redirect_uri)
        res = self.client.get(url, HTTP_HOST='testserver',
                              HTTP_AUTHORIZATION=auth_header)
        eq_(res.status_code, 401)
        assert not Token.objects.filter(token_type=ACCESS_TOKEN).exists()

    def test_token_request(self):
        url = settings.SITE_URL + reverse(
            'mkt.developers.oauth_token_request')
        url, auth_header = self._oauth_request_info(
            url, client_key=self.access.key, client_secret=self.access.secret,
            callback_uri=self.access.redirect_uri)
        res = self.client.get(url, HTTP_HOST='testserver',
                              HTTP_AUTHORIZATION=auth_header)
        eq_(res.status_code, 200)
        data = dict(urlparse.parse_qsl(res.content))
        assert Token.objects.filter(
            token_type=REQUEST_TOKEN,
            key=data['oauth_token'],
            secret=data['oauth_token_secret'],
            creds=self.access).exists()

    def test_bad_token_request(self):
        url = settings.SITE_URL + reverse(
            'mkt.developers.oauth_token_request')
        url, auth_header = self._oauth_request_info(
            url, client_key=self.access.key, client_secret=generate(),
            callback_uri=self.access.redirect_uri)

        res = self.client.get(url, HTTP_HOST='testserver',
                              HTTP_AUTHORIZATION=auth_header)
        eq_(res.status_code, 401)
        assert not Token.objects.filter(token_type=REQUEST_TOKEN).exists()
