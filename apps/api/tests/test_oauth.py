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
import urllib
import urlparse

from django import forms
from django.conf import settings
from django.core import mail
from django.test.client import (encode_multipart, Client, FakePayload,
                                BOUNDARY, MULTIPART_CONTENT)

import oauth2 as oauth
from mock import Mock, patch
from nose.tools import eq_
from test_utils import TestCase
from piston.models import Consumer, Token

from amo.urlresolvers import reverse
from addons.models import Addon, BlacklistedGuid
from translations.models import Translation
from versions.models import AppVersion, Version


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

    def delete(self, url, consumer=None, token=None, callback=False,
               verifier=None):
        url = get_absolute_url(url)
        req = oauth.Request(method='DELETE', url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))
        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)
        return super(OAuthClient, self).delete(req.to_url(), HTTP_HOST='api',
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
            verifier=None, data={}, content_type=MULTIPART_CONTENT, **kwargs):
        """
        Send a resource to the server using PUT.
        """
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        req = oauth.Request(method='PUT', url=url, parameters=params)

        signature_method = oauth.SignatureMethod_HMAC_SHA1()
        req.sign_request(signature_method, consumer, token)

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


class BasePiston(TestCase):
    """Base TestCase class for Piston."""
    fixtures = ('base/users', 'base/appversion', 'base/platforms',
                'base/licenses')

    def _login(self):
        self.client.login(username='admin@mozilla.com', password='password')


class BaseOauth(BasePiston):

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


def create_data():
    f = open(os.path.join(settings.ROOT,
                          'apps/api/fixtures/api/helloworld.xpi'))
    return dict(builtin=0, name='FREEDOM', text='This is FREE!',
                   platform='mac', xpi=f,)

class TestAddon(BaseOauth):

    def setUp(self):
        super(TestAddon, self).setUp()
        consumer = self.accepted_consumer
        self._oauth_flow(consumer)

        path = 'apps/api/fixtures/api/helloworld-0.2.xpi'
        self.version_data = dict(
                builtin=2,
                platform='windows',
                xpi=open(os.path.join(settings.ROOT, path)),
                )

    def make_create_request(self, data):
        return client.post('api.addons', self.accepted_consumer, self.token,
                           data=data)

    def create_addon(self):
        r = self.make_create_request(create_data())
        eq_(r.status_code, 200, r.content)
        return json.loads(r.content)

    def test_create(self):
        # License (req'd): MIT, GPLv2, GPLv3, LGPLv2.1, LGPLv3, MIT, BSD, Other
        # Custom License (if other, req'd)
        # XPI file... (req'd)
        # Platform (All by default): 'mac', 'all', 'bsd', 'linux', 'solaris',
        #   'windows'

        data = self.create_addon()
        id = data['id']
        name = data['name']
        eq_(name, 'XUL School Hello World')
        assert Addon.objects.get(pk=id)

    def test_create_nolicense(self):
        data = {}

        r = self.make_create_request(data)
        eq_(r.status_code, 400, r.content)
        eq_(r.content, 'Bad Request: '
            'Invalid data provided: This field is required. (builtin)')

    def test_delete(self):
        data = self.create_addon()
        id = data['id']
        guid = data['guid']

        r = client.delete(('api.addon', id), self.accepted_consumer,
                          self.token)
        eq_(r.status_code, 204, r.content)
        eq_(Addon.objects.filter(pk=id).count(), 0, "Didn't delete.")

        assert BlacklistedGuid.objects.filter(guid=guid)
        eq_(len(mail.outbox), 1)

    def test_update(self):
        # create an addon
        data = self.create_addon()
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

    @patch('api.handlers.AddonForm.is_valid')
    def test_update_fail(self, is_valid):
        data = self.create_addon()
        id = data['id']
        is_valid.return_value = False
        r = client.put(('api.addon', id), self.accepted_consumer, self.token,
                       data=data)
        eq_(r.status_code, 400, r.content)

    def test_update_nonexistant(self):
        r = client.put(('api.addon', 0), self.accepted_consumer, self.token,
                       data={})
        eq_(r.status_code, 410, r.content)

    @patch('api.handlers.XPIForm.clean_xpi')
    def test_xpi_failure(self, f):
        f.side_effect = forms.ValidationError('F')
        r = self.make_create_request(create_data())
        eq_(r.status_code, 400)

    def test_fake_license(self):
        data = create_data()
        data['builtin'] = 'fff'

        r = self.make_create_request(data)
        eq_(r.status_code, 400, r.content)
        eq_(r.content, 'Bad Request: Invalid data provided: '
            'Select a valid choice. fff is not one of the available choices. '
            '(builtin)')

    @patch('zipfile.ZipFile.namelist')
    def test_bad_zip(self, namelist):
        namelist.return_value = ('..', )
        r = self.make_create_request(create_data())
        eq_(r.status_code, 400, r.content)

    @patch('versions.models.AppVersion.objects.get')
    def test_bad_appversion(self, get):
        get.side_effect = AppVersion.DoesNotExist()
        data = self.create_addon()
        assert data, "We didn't get data."

    def test_wrong_guid(self):
        data = self.create_addon()
        id = data['id']
        addon = Addon.objects.get(pk=id)
        addon.guid = 'XXX'
        addon.save()

        # Upload new version of file
        r = client.post(('api.versions', id,), self.accepted_consumer,
                        self.token, data=self.version_data)
        eq_(r.status_code, 400)
        eq_(r.content, 'Bad Request: Add-on did not validate: '
            "GUID doesn't match add-on")

    def test_duplicate_guid(self):
        self.create_addon()
        data = create_data()
        data['xpi'] = self.version_data['xpi']
        r = self.make_create_request(data)
        eq_(r.status_code, 400)
        eq_(r.content, 'Bad Request: Add-on did not validate: '
            'Duplicate GUID found.')

    def test_create_version(self):
        # Create an addon and let's use this for the new version.
        data = self.create_addon()
        id = data['id']

        # Upload new version of file
        r = client.post(('api.versions', id,), self.accepted_consumer,
                        self.token, data=self.version_data)

        eq_(r.status_code, 200, r.content)
        # validate that the addon has 2 versions
        a = Addon.objects.get(pk=id)
        eq_(a.versions.all().count(), 2)

        # validate the version number
        v = a.versions.get(version='0.2')
        eq_(v.version, '0.2')
        # validate any new version data
        eq_(v.files.get().amo_platform.shortname, 'windows')

    def test_create_version_bad_license(self):
        data = self.create_addon()
        id = data['id']
        data = self.version_data.copy()
        data['builtin'] = 'fu'
        r = client.post(('api.versions', id,), self.accepted_consumer,
                        self.token, data=data)

        eq_(r.status_code, 400, r.content)

    def test_update_version_bad_license(self):
        data = self.create_addon()
        id = data['id']
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        path = 'apps/api/fixtures/api/helloworld-0.2.xpi'
        data = dict(
                release_notes='fukyeah',
                license_type='FFFF',
                platform='windows',
                xpi=open(os.path.join(settings.ROOT, path)),
                )
        r = client.put(('api.version', id, v.id), self.accepted_consumer,
                       self.token, data=data, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 200, r.content)
        data = json.loads(r.content)
        id = data['id']
        v = Version.objects.get(pk=id)
        eq_(str(v.license.text), 'This is FREE!')

    def test_update_version(self):
        # Create an addon
        data = self.create_addon()
        id = data['id']

        # verify version
        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        eq_(v.version, '0.1')

        path = 'apps/api/fixtures/api/helloworld-0.2.xpi'
        data = dict(
                release_notes='fukyeah',
                license_type='bsd',
                platform='windows',
                xpi=open(os.path.join(settings.ROOT, path)),
                )

        # upload new version
        r = client.put(('api.version', id, v.id), self.accepted_consumer,
                       self.token, data=data, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 200, r.content[:1000])

        # verify data
        v = a.versions.get()
        eq_(v.version, '0.2')
        eq_(str(v.releasenotes), 'fukyeah')

    def test_update_version_compatability(self):
        # Create an addon
        data = self.create_addon()
        id = data['id']

        # verify version
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        eq_(v.version, '0.1')
        data = {
                'form-TOTAL_FORMS': 1,
                'form-INITIAL_FORMS': 1,
                'form-MAX_NUM_FORMS': '',
                'form-0-id': v.apps.get().id,
                'form-0-min': 311,
                'form-0-max': 313,
                'form-0-application': 1,
               }
        # upload new version
        r = client.put(('api.compatibility', id, v.id), self.accepted_consumer,
                       self.token, data=data, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 200, r.content[:1000])
        data = json.loads(r.content)

        eq_(data[0]['application'], 'firefox')
        eq_(data[0]['min'], '3.7a3')
        eq_(data[0]['max'], '3.7a4')

    def test_update_version_bad_xpi(self):
        data = self.create_addon()
        id = data['id']

        # verify version
        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        eq_(v.version, '0.1')

        data = dict(
                release_notes='fukyeah',
                license_type='bsd',
                platform='windows',
                )

        # upload new version
        r = client.put(('api.version', id, v.id), self.accepted_consumer,
                       self.token, data=data, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 400)

    def test_update_version_bad_id(self):
        r = client.put(('api.version', 0, 0), self.accepted_consumer,
                       self.token, data={}, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 410, r.content)

    @patch('access.acl.check_ownership')
    def test_not_my_addon(self, acl):
        data = self.create_addon()
        id = data['id']
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        acl.return_value = False

        r = client.put(('api.version', id, v.id), self.accepted_consumer,
                       self.token, data={}, content_type=MULTIPART_CONTENT)
        eq_(r.status_code, 401, r.content)

        r = client.put(('api.addon', id), self.accepted_consumer, self.token,
                       data=data)
        eq_(r.status_code, 401, r.content)

    def test_delete_version(self):
        data = self.create_addon()
        id = data['id']

        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        r = client.delete(('api.version', id, v.id), self.accepted_consumer,
                          self.token)
        eq_(r.status_code, 204, r.content)
        eq_(a.versions.count(), 0)

    def test_retrieve_versions(self):
        data = self.create_addon()
        id = data['id']

        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        r = client.get(('api.versions', id), self.accepted_consumer,
                       self.token)
        eq_(r.status_code, 200, r.content)
        data = json.loads(r.content)
        for attr in ('id', 'version',):
            expect = getattr(v, attr)
            val = data[0].get(attr)
            eq_(expect, val,
                'Got "%s" was expecting "%s" for "%s".' % (val, expect, attr,))


class TestAddonSansOauth(BasePiston):
    """OAuth is not required if you are logged in.  So let's try some stuff."""

    def create_addon(self):
        self._login()
        r = self.client.post(reverse('api.addons'), create_data())
        eq_(r.status_code, 200, r.content)
        return json.loads(r.content)

    def test_update_version_compatability_bad_form(self):
        data = self.create_addon()
        id = data['id']

        # verify version
        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        eq_(v.version, '0.1')
        # upload new version
        r = self.client.put(reverse('api.compatibility', args=(id, v.id,)))
        eq_(r.status_code, 400, r.content[:1000])
        eq_(r.content, 'Bad Request: No data')

    def test_version_anonymous(self):
        r = self.client.get(reverse('api.versions', args=(999,)))
        eq_(r.status_code, 410)

        data = self.create_addon()
        id = data['id']

        self.client.logout()
        r = self.client.get(reverse('api.versions', args=(id,)))
        eq_(r.status_code, 200)
        a = Addon.objects.get()
        v = a.versions.get()
        r = self.client.get(reverse('api.version', args=(id, v.id)))
        eq_(r.status_code, 200)
        r = self.client.get(reverse('api.version', args=(id, 999)))
        eq_(r.status_code, 410)
