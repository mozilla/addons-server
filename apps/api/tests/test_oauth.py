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
                                BOUNDARY, MULTIPART_CONTENT, RequestFactory)

import oauth2 as oauth
from mock import Mock, patch
from piston.models import Consumer

import amo
from amo.helpers import absolutify
from amo.tests import TestCase
from amo.urlresolvers import reverse
from api.authentication import AMOOAuthAuthentication
from addons.models import Addon, AddonUser
from devhub.models import ActivityLog, SubmitStep
from files.models import File
from translations.models import Translation
from users.models import UserProfile
from versions.models import AppVersion, Version
import pytest


def _get_args(consumer, token=None, callback=False, verifier=None):
    d = dict(oauth_consumer_key=consumer.key,
             oauth_nonce=oauth.generate_nonce(),
             oauth_signature_method='HMAC-SHA1',
             oauth_timestamp=int(time.time()),
             oauth_version='1.0')

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
        return super(OAuthClient, self).get(
            req.to_url(), HTTP_HOST='api', HTTP_AUTHORIZATION='OAuth realm=""',
            **req)

    def delete(self, url, consumer=None, token=None, callback=False,
               verifier=None):
        url = get_absolute_url(url)
        req = oauth.Request(method='DELETE', url=url,
                            parameters=_get_args(consumer, callback=callback,
                                                 verifier=verifier))
        req.sign_request(self.signature_method, consumer, token)
        return super(OAuthClient, self).delete(
            req.to_url(), HTTP_HOST='api', HTTP_AUTHORIZATION='OAuth realm=""',
            **req)

    def post(self, url, consumer=None, token=None, callback=False,
             verifier=None, data={}):
        url = get_absolute_url(url)
        params = _get_args(consumer, callback=callback, verifier=verifier)
        params.update(data_keys(data))
        req = oauth.Request(method='POST', url=url, parameters=params)
        req.sign_request(self.signature_method, consumer, token)
        return super(OAuthClient, self).post(
            req.to_url(), HTTP_HOST='api', HTTP_AUTHORIZATION='OAuth realm=""',
            data=data, headers=req.to_header())

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
            'CONTENT_TYPE': content_type,
            'PATH_INFO': urllib.unquote(parsed[2]),
            'QUERY_STRING': query_string,
            'REQUEST_METHOD': 'PUT',
            'wsgi.input': FakePayload(post_data),
            'HTTP_HOST': 'api',
            'HTTP_AUTHORIZATION': 'OAuth realm=""',
        }
        r.update(req)

        response = self.request(**r)
        return response

oclient = OAuthClient()
token_keys = ('oauth_token_secret', 'oauth_token',)


def get_token_from_response(response):
    data = urlparse.parse_qs(response.content)
    for key in token_keys:
        assert key in data.keys(), '%s not in %s' % (key, data.keys())

    return oauth.Token(key=data['oauth_token'][0],
                       secret=data['oauth_token_secret'][0])


def get_request_token(consumer, callback=False):
    r = oclient.get('oauth.request_token', consumer, callback=callback)
    return get_token_from_response(r)


def get_access_token(consumer, token, authorize=True, verifier=None):
    r = oclient.get('oauth.access_token', consumer, token, verifier=verifier)

    if authorize:
        return get_token_from_response(r)
    else:
        assert r.status_code == 401


class BaseOAuth(TestCase):
    fixtures = ['base/users', 'base/appversion', 'base/licenses']

    def setUp(self):
        super(BaseOAuth, self).setUp()
        self.editor = UserProfile.objects.get(email='editor@mozilla.com')
        self.admin = UserProfile.objects.get(email='admin@mozilla.com')
        consumers = []
        for status in ('accepted', 'pending', 'canceled', ):
            c = Consumer(name='a', status=status, user=self.editor)
            c.generate_random_codes()
            c.save()
            consumers.append(c)
        self.accepted_consumer = consumers[0]
        self.pending_consumer = consumers[1]
        self.canceled_consumer = consumers[2]
        self.token = None


class TestBaseOAuth(BaseOAuth):

    def test_accepted(self):
        with pytest.raises(AssertionError):
            get_request_token(self.accepted_consumer)

    def test_accepted_callback(self):
        get_request_token(self.accepted_consumer, callback=True)

    def test_request_token_pending(self):
        get_request_token(self.pending_consumer, callback=True)

    def test_request_token_cancelled(self):
        get_request_token(self.canceled_consumer, callback=True)

    def test_request_token_fake(self):
        """Try with a phony consumer key"""
        c = Mock()
        c.key = 'yer'
        c.secret = 'mom'
        r = oclient.get('oauth.request_token', c, callback=True)
        assert r.content == 'Invalid Consumer.'

    @patch('piston.authentication.oauth.OAuthAuthentication.is_authenticated')
    def _test_auth(self, pk, is_authenticated, two_legged=True):
        request = RequestFactory().get('/en-US/firefox/2/api/2/user/',
                                       data={'authenticate_as': pk})
        request.user = None

        def alter_request(*args, **kw):
            request.user = self.admin
            return True
        is_authenticated.return_value = True
        is_authenticated.side_effect = alter_request

        auth = AMOOAuthAuthentication()
        auth.two_legged = two_legged
        auth.is_authenticated(request)
        return request

    def test_login_nonexistant(self):
        assert self.admin == self._test_auth(9999).user

    def test_login_deleted(self):
        # If _test_auth returns self.admin, that means the user was
        # not altered to the user set in authenticate_as.
        self.editor.update(deleted=True)
        pk = self.editor.pk
        assert self.admin == self._test_auth(pk).user

    def test_login_unconfirmed(self):
        self.editor.update(confirmationcode='something')
        pk = self.editor.pk
        assert self.admin == self._test_auth(pk).user

    def test_login_works(self):
        pk = self.editor.pk
        assert self.editor == self._test_auth(pk).user

    def test_login_three_legged(self):
        pk = self.editor.pk
        assert self.admin == self._test_auth(pk, two_legged=False).user


class TestUser(BaseOAuth):

    def test_user(self):
        r = oclient.get('api.user', self.accepted_consumer, self.token)
        assert json.loads(r.content)['email'] == 'editor@mozilla.com'

    def test_user_lookup(self):
        partner = UserProfile.objects.get(email='partner@mozilla.com')
        c = Consumer(name='p', status='accepted', user=partner)
        c.generate_random_codes()
        c.save()
        r = oclient.get('api.user', c, None,
                        params={'email': 'admin@mozilla.com'})
        assert r.status_code == 200
        assert json.loads(r.content)['email'] == 'admin@mozilla.com'

    def test_failed_user_lookup(self):
        partner = UserProfile.objects.get(email='partner@mozilla.com')
        c = Consumer(name='p', status='accepted', user=partner)
        c.generate_random_codes()
        c.save()
        r = oclient.get('api.user', c, None,
                        params={'email': 'not_a_user@mozilla.com'})
        assert r.status_code == 404

    def test_forbidden_user_lookup(self, response_code=401):
        r = oclient.get('api.user', self.accepted_consumer, self.token,
                        params={'email': 'admin@mozilla.com'})
        assert r.status_code == response_code


class TestDRFUser(TestUser):

    def setUp(self):
        super(TestDRFUser, self).setUp()
        self.create_switch('drf')

    def test_forbidden_user_lookup(self):
        super(TestDRFUser, self).test_forbidden_user_lookup(response_code=403)


def activitylog_count(type=None):
    qs = ActivityLog.objects
    if type:
        qs = qs.filter(action=type.id)
    return qs.count()


class TestAddon(BaseOAuth):
    created_http_status = 200
    permission_denied_http_status = 401

    def setUp(self):
        super(TestAddon, self).setUp()
        path = 'apps/files/fixtures/files/extension.xpi'
        xpi = os.path.join(settings.ROOT, path)
        f = open(xpi)

        self.create_data = dict(builtin=0,
                                name='FREEDOM',
                                text='This is FREE!',
                                platform='mac',
                                xpi=f)

        path = 'apps/files/fixtures/files/extension-0.2.xpi'
        self.version_data = dict(builtin=2, platform='windows',
                                 xpi=open(os.path.join(settings.ROOT, path)))
        self.update_data = dict(name='fu',
                                default_locale='fr',
                                homepage='mozilla.com',
                                support_email='go@away.com',
                                support_url='http://google.com/',
                                description='awesome',
                                summary='sucks',
                                developer_comments='i made it for you',
                                eula='love it',
                                privacy_policy='aybabtu',
                                the_reason='for shits',
                                the_future='is gone',
                                view_source=1,
                                prerelease=1,
                                binary=False,
                                site_specific=1)

    def make_create_request(self, data):
        return oclient.post('api.addons', self.accepted_consumer, self.token,
                            data=data)

    def create_addon(self):
        current_count = activitylog_count(amo.LOG.CREATE_ADDON)
        r = self.make_create_request(self.create_data)
        assert r.status_code == self.created_http_status
        assert activitylog_count(amo.LOG.CREATE_ADDON) == current_count + 1
        return json.loads(r.content)

    def test_create_no_user(self):
        # The user in TwoLeggedAuth is set to the consumer user.
        # If there isn't one, we should get a challenge back.
        self.accepted_consumer.user = None
        self.accepted_consumer.save()
        r = self.make_create_request(self.create_data)
        assert r.status_code == 401

    def test_create_user_altered(self):
        data = self.create_data
        data['authenticate_as'] = self.editor.pk
        r = self.make_create_request(data)
        assert r.status_code == self.created_http_status

        id = json.loads(r.content)['id']
        ad = Addon.objects.get(pk=id)
        assert len(ad.authors.all()) == 1
        assert ad.authors.all()[0].pk == self.editor.pk

    def test_create(self):
        # License (req'd): MIT, GPLv2, GPLv3, LGPLv2.1, LGPLv3, MIT, BSD, Other
        # Custom License (if other, req'd)
        # XPI file... (req'd)
        # Platform (All by default): 'mac', 'all', 'bsd', 'linux', 'solaris',
        #   'windows'

        data = self.create_addon()
        id = data['id']
        name = data['name']
        assert name == 'xpi name'
        assert Addon.objects.get(pk=id)

    def create_no_license(self):
        data = self.create_data.copy()
        del data['builtin']
        return self.make_create_request(data)

    def test_create_no_license(self):
        r = self.create_no_license()
        assert r.status_code == self.created_http_status
        assert Addon.objects.count() == 1

    def test_create_no_license_step(self):
        r = self.create_no_license()
        assert r.status_code == self.created_http_status
        id = json.loads(r.content)['id']
        assert SubmitStep.objects.get(addon=id).step == 5

    def test_create_no_license_url(self):
        self.create_no_license()
        self.client.login(username='editor@mozilla.com', password='password')
        res = self.client.get(reverse('devhub.submit.resume',
                                      args=['xpi-name']))
        self.assert3xx(res, reverse('devhub.submit.5', args=['xpi-name']))

    def test_create_no_license_status(self):
        self.create_no_license()
        assert Addon.objects.get(slug='xpi-name').status == 0

    def test_create_status(self):
        r = self.make_create_request(self.create_data)
        assert r.status_code == self.created_http_status
        assert Addon.objects.get(slug='xpi-name').status == 0
        assert Addon.objects.count() == 1

    def test_create_slug(self):
        r = self.make_create_request(self.create_data)
        content = json.loads(r.content)
        assert content['slug'] == 'xpi-name'
        assert content['resource_uri'] == absolutify(reverse('addons.detail', args=['xpi-name']))

    def test_delete(self):
        data = self.create_addon()
        id = data['id']
        # Force it to be public so an email gets sent.
        Addon.objects.filter(id=id).update(highest_status=amo.STATUS_PUBLIC)

        r = oclient.delete(('api.addon', id), self.accepted_consumer,
                           self.token)
        assert r.status_code == 204
        assert Addon.objects.filter(pk=id).count() == 0

        assert len(mail.outbox) == 1

    def test_update(self):
        # create an addon
        data = self.create_addon()
        id = data['id']

        current_count = activitylog_count()
        r = oclient.put(('api.addon', id), self.accepted_consumer, self.token,
                        data=self.update_data)
        assert r.status_code == 200
        assert activitylog_count() == current_count + 1

        a = Addon.objects.get(pk=id)
        for field, expected in self.update_data.iteritems():
            value = getattr(a, field)
            if isinstance(value, Translation):
                value = unicode(value)

            assert value == expected

    @patch('api.handlers.AddonForm.is_valid')
    def test_update_fail(self, is_valid):
        data = self.create_addon()
        id = data['id']
        is_valid.return_value = False
        r = oclient.put(('api.addon', id), self.accepted_consumer, self.token,
                        data=self.update_data)
        assert r.status_code == 400

    def test_update_nonexistant(self):
        r = oclient.put(('api.addon', 0), self.accepted_consumer, self.token,
                        data={})
        assert r.status_code == 410

    @patch('api.handlers.XPIForm.clean_xpi')
    def test_xpi_failure(self, f):
        f.side_effect = forms.ValidationError('F')
        r = self.make_create_request(self.create_data)
        assert r.status_code == 400

    def test_fake_license(self):
        data = self.create_data.copy()
        data['builtin'] = 'fff'

        r = self.make_create_request(data)
        assert r.status_code == 400
        assert r.content == 'Bad Request: Invalid data provided: ' 'Select a valid choice. fff is not one of the available choices. ' '(builtin)'

    @patch('zipfile.ZipFile.infolist')
    def test_bad_zip(self, infolist):
        fake = Mock()
        fake.filename = '..'
        infolist.return_value = [fake]
        r = self.make_create_request(self.create_data)
        assert r.status_code == 400

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
        r = oclient.post(('api.versions', id,), self.accepted_consumer,
                         self.token, data=self.version_data)
        assert r.status_code == 400
        assert r.content == 'Bad Request: Add-on did not validate: ' "Add-on ID doesn't match add-on."

    def test_duplicate_guid(self):
        self.create_addon()
        data = self.create_data.copy()
        data['xpi'] = self.version_data['xpi']
        r = self.make_create_request(data)
        assert r.status_code == 400
        assert r.content == 'Bad Request: Add-on did not validate: ' 'Duplicate add-on ID found.'

    def test_create_version(self):
        # Create an addon and let's use this for the new version.
        data = self.create_addon()
        id = data['id']

        log_count = activitylog_count()

        # Upload new version of file
        r = oclient.post(('api.versions', id,), self.accepted_consumer,
                         self.token, data=self.version_data)
        assert r.status_code == 200
        assert log_count + 2 == activitylog_count()

        # validate that the addon has 2 versions
        a = Addon.objects.get(pk=id)
        assert a.versions.all().count() == 2

        # validate the version number
        v = a.versions.get(version='0.2')
        assert v.version == '0.2'
        assert amo.PLATFORMS[v.files.get().platform].shortname == 'windows'

    def test_create_version_bad_license(self):
        data = self.create_addon()
        id = data['id']
        data = self.version_data.copy()
        data['builtin'] = 'fu'
        r = oclient.post(('api.versions', id,), self.accepted_consumer,
                         self.token, data=data)
        assert r.status_code == 400

    def test_create_version_no_license(self):
        data = self.create_addon()
        id = data['id']
        data = self.version_data.copy()
        del data['builtin']
        r = oclient.post(('api.versions', id,), self.accepted_consumer,
                         self.token, data=data)
        assert r.status_code == 200
        data = json.loads(r.content)
        id = data['id']
        v = Version.objects.get(pk=id)
        assert not v.license

    def create_for_update(self):
        data = self.create_addon()
        id = data['id']
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        assert v.version == '0.1'
        return a, v, 'apps/files/fixtures/files/extension-0.2.xpi'

    def test_update_version_no_license(self):
        a, v, path = self.create_for_update()
        data = dict(release_notes='fukyeah', platform='windows',
                    xpi=open(os.path.join(settings.ROOT, path)))
        r = oclient.put(('api.version', a.id, v.id), self.accepted_consumer,
                        self.token, data=data, content_type=MULTIPART_CONTENT)
        assert r.status_code == 200
        v = a.versions.get()
        assert v.version == '0.2'
        assert v.license is None

    def test_update_version_bad_license(self):
        a, v, path = self.create_for_update()
        data = dict(release_notes='fukyeah', builtin=3, platform='windows',
                    xpi=open(os.path.join(settings.ROOT, path)))
        r = oclient.put(('api.version', a.id, v.id), self.accepted_consumer,
                        self.token, data=data, content_type=MULTIPART_CONTENT)
        assert r.status_code == 400

    def test_update_version(self):
        a, v, path = self.create_for_update()
        data = dict(release_notes='fukyeah', builtin=2, platform='windows',
                    xpi=open(os.path.join(settings.ROOT, path)))
        log_count = activitylog_count()
        # upload new version
        r = oclient.put(('api.version', a.id, v.id), self.accepted_consumer,
                        self.token, data=data, content_type=MULTIPART_CONTENT)
        assert r.status_code == 200
        assert activitylog_count() == log_count + 2
        # verify data
        v = a.versions.get()
        assert v.version == '0.2'
        assert str(v.releasenotes) == 'fukyeah'
        assert str(v.license.builtin) == '2'

    def test_update_version_bad_xpi(self):
        data = self.create_addon()
        id = data['id']

        # verify version
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        assert v.version == '0.1'

        data = dict(release_notes='fukyeah', platform='windows')

        # upload new version
        r = oclient.put(('api.version', id, v.id), self.accepted_consumer,
                        self.token, data=data, content_type=MULTIPART_CONTENT)
        assert r.status_code == 400

    def test_update_version_bad_id(self):
        r = oclient.put(('api.version', 0, 0), self.accepted_consumer,
                        self.token, data={}, content_type=MULTIPART_CONTENT)
        assert r.status_code == 410

    def test_get_version(self):
        data = self.create_addon()
        a = Addon.objects.get(pk=data['id'])
        r = oclient.get(('api.version', data['id'], a.versions.get().id),
                        self.accepted_consumer, self.token)
        assert r.status_code == 200

    def test_get_version_statuses(self):
        data = self.create_addon()
        a = Addon.objects.get(pk=data['id'])
        r = oclient.get(('api.version', data['id'], a.versions.get().id),
                        self.accepted_consumer, self.token)
        assert json.loads(r.content)['statuses'] == [[File.objects.all()[0].pk, 1]]

    @patch('api.authorization.AllowRelatedAppOwner.has_object_permission')
    @patch('api.authorization.AllowAppOwner.has_object_permission')
    @patch('access.acl.action_allowed')
    @patch('access.acl.check_addon_ownership')
    def test_not_my_addon(self, addon_ownership, action_allowed,
                          app_owner, related_app_owner):
        data = self.create_addon()
        id = data['id']
        a = Addon.objects.get(pk=id)
        v = a.versions.get()
        # The first one is for piston, the 3 next ones are for DRF.
        addon_ownership.return_value = False
        action_allowed.return_value = False
        app_owner.return_value = False
        related_app_owner.return_value = False

        r = oclient.put(('api.version', id, v.id), self.accepted_consumer,
                        self.token, data={}, content_type=MULTIPART_CONTENT)
        assert r.status_code == self.permission_denied_http_status

        r = oclient.put(('api.addon', id), self.accepted_consumer, self.token,
                        data=self.update_data)
        assert r.status_code == self.permission_denied_http_status

    def test_delete_version(self):
        data = self.create_addon()
        id = data['id']

        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        log_count = activitylog_count()
        r = oclient.delete(('api.version', id, v.id), self.accepted_consumer,
                           self.token)
        assert activitylog_count() == log_count + 1
        assert r.status_code == 204
        assert a.versions.count() == 0

    def test_retrieve_versions(self):
        data = self.create_addon()
        id = data['id']

        a = Addon.objects.get(pk=id)
        v = a.versions.get()

        r = oclient.get(('api.versions', id), self.accepted_consumer,
                        self.token)
        assert r.status_code == 200
        data = json.loads(r.content)
        for attr in ('id', 'version',):
            expect = getattr(v, attr)
            val = data[0].get(attr)
            assert expect == val

    def test_no_addons(self):
        r = oclient.get('api.addons', self.accepted_consumer, self.token)
        assert json.loads(r.content)['count'] == 0

    def test_no_user(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon=addon, user=self.admin,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = oclient.get('api.addons', self.accepted_consumer, self.token)
        assert json.loads(r.content)['count'] == 0

    def test_my_addons_only(self):
        for num in range(0, 2):
            addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon=addon, user=self.editor,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = oclient.get('api.addons', self.accepted_consumer, self.token,
                        params={'authenticate_as': self.editor.pk})
        j = json.loads(r.content)
        assert j['count'] == 1
        assert j['objects'][0]['id'] == addon.id

    def test_one_addon(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon=addon, user=self.editor,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = oclient.get(('api.addon', addon.pk), self.accepted_consumer,
                        self.token, params={'authenticate_as': self.editor.pk})
        assert json.loads(r.content)['id'] == addon.pk

    def test_my_addons_role(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon=addon, user=self.editor,
                                 role=amo.AUTHOR_ROLE_VIEWER)
        r = oclient.get('api.addons', self.accepted_consumer, self.token)
        assert json.loads(r.content)['count'] == 0

    def test_my_addons_disabled(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_DISABLED)
        AddonUser.objects.create(addon=addon, user=self.editor,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = oclient.get('api.addons', self.accepted_consumer, self.token)
        assert json.loads(r.content)['count'] == 0

    def test_my_addons_deleted(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_DELETED)
        AddonUser.objects.create(addon=addon, user=self.editor,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = oclient.get('api.addons', self.accepted_consumer, self.token)
        assert json.loads(r.content)['count'] == 0


class TestDRFAddon(TestAddon):
    created_http_status = 201
    permission_denied_http_status = 403

    def setUp(self):
        super(TestDRFAddon, self).setUp()
        self.create_switch('drf')

    def _compare_dicts(self, drf_data, piston_data):
        """
        Given 2 dicts of data from DRF and Piston, compare keys then values.
        """
        assert sorted(drf_data.keys()) == sorted(piston_data.keys())
        for drf_item, piston_item in zip(sorted(drf_data.items()),
                                         sorted(piston_data.items())):
            assert drf_item[0] == piston_item[0]
            assert drf_item[1] == piston_item[1]

    def compare_output(self, url, listed=False):
        """
        Load responses from DRF and Piston given the `url` parameter and
        compare returned data dicts, key by key. Useful to make sure
        that both responses are similar.

        Set `listed` to True for comparing responses as lists.
        """
        r = oclient.get(url, self.accepted_consumer, self.token)
        assert r.status_code == 200
        drf_data = json.loads(r.content)
        self.create_switch('drf', **{'active': False})
        r = oclient.get(url, self.accepted_consumer, self.token)
        assert r.status_code == 200
        piston_data = json.loads(r.content)
        if listed:
            assert len(drf_data) == len(piston_data)
            for items in zip(drf_data, piston_data):
                self._compare_dicts(items[0], items[1])
        else:
            self._compare_dicts(drf_data, piston_data)

    def test_diff_versions(self):
        data = self.create_addon()
        self.compare_output(('api.versions', data['id']), listed=True)

    def test_diff_version(self):
        data = self.create_addon()
        addon = Addon.objects.get(pk=data['id'])
        version = addon.versions.get()
        self.compare_output(('api.version', addon.id, version.id))

    def test_diff_addons(self):
        self.create_addon()
        self.compare_output(('api.addons'))

    def test_diff_addon(self):
        data = self.create_addon()
        self.compare_output(('api.addon', data['id']))
