# -*- coding: utf-8 -*-
import json
import re
import sys

from unittest import mock
from urllib.parse import urlparse

import django
from django import test
from django.conf import settings
from django.test.utils import override_settings
from django.utils.encoding import force_text

import pytest

from lxml import etree
from unittest.mock import patch
from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser, get_random_slug
from olympia.amo.tests import (
    APITestClient, TestCase, WithDynamicEndpointsAndTransactions, check_links,
    reverse_ns)
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile
from olympia.zadmin.models import set_config


@pytest.mark.django_db
@pytest.mark.parametrize('locale', list(settings.LANGUAGES))
def test_locale_switcher(client, locale):
    response = client.get('/{}/developers/'.format(locale))
    assert response.status_code == 200


class Test403(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(Test403, self).setUp()
        assert self.client.login(email='regular@mozilla.com')

    def test_403_no_app(self):
        response = self.client.get('/en-US/admin/')
        assert response.status_code == 403
        self.assertTemplateUsed(response, 'amo/403.html')

    def test_403_app(self):
        response = self.client.get('/en-US/android/admin/', follow=True)
        assert response.status_code == 403
        self.assertTemplateUsed(response, 'amo/403.html')


class Test404(TestCase):

    def test_404_no_app(self):
        """Make sure a 404 without an app doesn't turn into a 500."""
        # That could happen if helpers or templates expect APP to be defined.
        url = reverse('amo.monitor')
        response = self.client.get(url + 'nonsense')
        assert response.status_code == 404
        self.assertTemplateUsed(response, 'amo/404.html')

    def test_404_app_links(self):
        res = self.client.get('/en-US/android/xxxxxxx')
        assert res.status_code == 404
        self.assertTemplateUsed(res, 'amo/404.html')
        links = pq(res.content)('[role=main] ul a[href^="/en-US/android"]')
        assert links.length == 4

    def test_404_api_v3(self):
        response = self.client.get('/api/v3/lol')
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == u'Not found.'

    def test_404_api_v4(self):
        response = self.client.get('/api/v4/lol')
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == u'Not found.'

    def test_404_with_mobile_detected(self):
        res = self.client.get('/en-US/firefox/xxxxxxx', X_IS_MOBILE_AGENTS='1')
        assert res.status_code == 404
        self.assertTemplateUsed(res, 'amo/404-responsive.html')

        res = self.client.get('/en-US/firefox/xxxxxxx', X_IS_MOBILE_AGENTS='0')
        assert res.status_code == 404
        self.assertTemplateUsed(res, 'amo/404.html')


class TestCommon(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestCommon, self).setUp()
        self.url = reverse('apps.appversions')

    def login(self, user=None, get=False):
        email = '%s@mozilla.com' % user
        super(TestCommon, self).login(email)
        if get:
            return UserProfile.objects.get(email=email)

    def test_tools_regular_user(self):
        self.login('regular')
        r = self.client.get(self.url, follow=True)
        assert not r.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'), verify=False)

    def test_tools_developer(self):
        # Make them a developer.
        user = self.login('regular', get=True)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        group = Group.objects.create(name='Staff', rules='Admin:Tools')
        GroupUser.objects.create(group=group, user=user)

        r = self.client.get(self.url, follow=True)
        assert r.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'), verify=False)

    def test_tools_reviewer(self):
        self.login('reviewer')
        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        assert not request.user.is_developer
        assert acl.action_allowed(request, amo.permissions.ADDONS_REVIEW)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'), verify=False)

    def test_tools_developer_and_reviewer(self):
        # Make them a developer.
        user = self.login('reviewer', get=True)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        assert request.user.is_developer
        assert acl.action_allowed(request, amo.permissions.ADDONS_REVIEW)

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'), verify=False)

    def test_tools_admin(self):
        self.login('admin')
        response = self.client.get(self.url, follow=True)
        assert response.status_code == 200
        request = response.context['request']
        assert not request.user.is_developer
        assert acl.action_allowed(request, amo.permissions.ADDONS_REVIEW)
        assert acl.action_allowed(request, amo.permissions.LOCALIZER)
        assert acl.action_allowed(request, amo.permissions.ANY_ADMIN)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('zadmin.index')),
        ]
        check_links(
            expected, pq(response.content)('#aux-nav .tools a'), verify=False)

    def test_tools_developer_and_admin(self):
        # Make them a developer.
        user = self.login('admin', get=True)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        response = self.client.get(self.url, follow=True)
        assert response.status_code == 200
        request = response.context['request']
        assert request.user.is_developer
        assert acl.action_allowed(request, amo.permissions.ADDONS_REVIEW)
        assert acl.action_allowed(request, amo.permissions.LOCALIZER)
        assert acl.action_allowed(request, amo.permissions.ANY_ADMIN)

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('zadmin.index')),
        ]
        check_links(
            expected, pq(response.content)('#aux-nav .tools a'), verify=False)


class TestOtherStuff(TestCase):
    # Tests that don't need fixtures.

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get('/en-US/firefox/pages/appversions/')
        doc = pq(response.content)
        assert doc('#site-notice').length == 0

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get('/en-US/firefox/pages/appversions/')
        doc = pq(response.content)
        assert doc('#site-notice').length == 1

    def test_heading(self):
        def title_eq(url, alt, text):
            response = self.client.get(url + 'pages/appversions/', follow=True)
            doc = pq(response.content)
            assert alt == doc('.site-title img').attr('alt')
            assert text == doc('.site-title').text()

        title_eq('/firefox/', 'Firefox', 'Add-ons')
        title_eq('/android/', 'Firefox for Android', 'Android Add-ons')

    @patch('olympia.accounts.utils.default_fxa_login_url',
           lambda request: 'https://login.com')
    def test_login_link(self):
        r = self.client.get(reverse('apps.appversions'), follow=True)
        doc = pq(r.content)
        assert 'https://login.com' == (
            doc('.account.anonymous a')[1].attrib['href'])

    def test_tools_loggedout(self):
        r = self.client.get(reverse('apps.appversions'), follow=True)
        assert pq(r.content)('#aux-nav .tools').length == 0

    def test_language_selector(self):
        doc = pq(test.Client().get(
            '/en-US/firefox/pages/appversions/').content)
        assert doc('form.languages option[selected]').attr('value') == 'en-us'

    def test_language_selector_variables(self):
        r = self.client.get(
            '/en-US/firefox/pages/appversions/?foo=fooval&bar=barval')
        doc = pq(r.content)('form.languages')

        assert doc('input[type=hidden][name=foo]').attr('value') == 'fooval'
        assert doc('input[type=hidden][name=bar]').attr('value') == 'barval'

    @patch.object(settings, 'KNOWN_PROXIES', ['127.0.0.1'])
    @patch.object(core, 'set_remote_addr')
    def test_remote_addr(self, set_remote_addr_mock):
        """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR."""
        client = test.Client()
        # Send X-Forwarded-For as it shows up in a wsgi request.
        client.get('/en-US/developers/', follow=True,
                   HTTP_X_FORWARDED_FOR='1.1.1.1',
                   REMOTE_ADDR='127.0.0.1')
        assert set_remote_addr_mock.call_count == 2
        assert set_remote_addr_mock.call_args_list[0] == (('1.1.1.1',), {})
        assert set_remote_addr_mock.call_args_list[1] == ((None,), {})

    def test_opensearch(self):
        client = test.Client()
        page = client.get('/en-US/firefox/opensearch.xml')

        wanted = ('Content-Type', 'text/xml')
        assert page._headers['content-type'] == wanted

        doc = etree.fromstring(page.content)
        e = doc.find("{http://a9.com/-/spec/opensearch/1.1/}ShortName")
        assert e.text == "Firefox Add-ons"


class TestCORS(TestCase):
    fixtures = ('base/addon_3615',)

    def get(self, url, **headers):
        return self.client.get(url, HTTP_ORIGIN='testserver', **headers)

    def test_no_cors(self):
        response = self.get(reverse('devhub.index'))
        assert response.status_code == 200
        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Allow-Credentials')

    def test_cors_api_v3(self):
        url = reverse_ns('addon-detail', api_version='v3', args=(3615,))
        assert '/api/v3/' in url
        response = self.get(url)
        assert response.status_code == 200
        assert not response.has_header('Access-Control-Allow-Credentials')
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_cors_api_v4(self):
        url = reverse_ns('addon-detail', api_version='v4', args=(3615,))
        assert '/api/v4/' in url
        response = self.get(url)
        assert response.status_code == 200
        assert not response.has_header('Access-Control-Allow-Credentials')
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_cors_excludes_accounts_session_endpoint(self):
        assert re.match(
            settings.CORS_URLS_REGEX,
            urlparse(reverse_ns('accounts.session')).path,
        ) is None


class TestContribute(TestCase):

    def test_contribute_json(self):
        res = self.client.get('/contribute.json')
        assert res.status_code == 200
        assert res._headers['content-type'] == (
            'Content-Type', 'application/json')


class TestRobots(TestCase):

    @override_settings(ENGAGE_ROBOTS=True)
    def test_disable_collections(self):
        """Make sure /en-US/firefox/collections/ gets disabled"""
        url = reverse('collections.list')
        response = self.client.get('/robots.txt')
        assert response.status_code == 200
        assert 'Disallow: %s' % url in response.content.decode('utf-8')

    @override_settings(ENGAGE_ROBOTS=True)
    def test_allow_mozilla_collections(self):
        """Make sure Mozilla collections are allowed"""
        url = '{}{}/'.format(reverse('collections.list'),
                             settings.TASK_USER_ID)
        response = self.client.get('/robots.txt')
        assert response.status_code == 200
        assert 'Allow: {}'.format(url) in response.content.decode('utf-8')


class TestAtomicRequests(WithDynamicEndpointsAndTransactions):

    def setUp(self):
        super(TestAtomicRequests, self).setUp()
        self.slug = get_random_slug()

    def _generate_view(self, method_that_will_be_tested):
        # A view should *not* be an instancemethod of a class, it prevents
        # attributes from being added, which in turns breaks
        # non_atomic_requests() silently.
        # So we generate one by returning a regular function instead.
        def actual_view(request):
            Addon.objects.create(slug=self.slug)
            raise RuntimeError(
                'pretend this is an unhandled exception happening in a view.')
        return actual_view

    def test_post_requests_are_wrapped_in_a_transaction(self):
        self.endpoint(self._generate_view('POST'))
        qs = Addon.objects.filter(slug=self.slug)
        assert not qs.exists()
        url = reverse('test-dynamic-endpoint')
        try:
            with self.assertRaises(RuntimeError):
                self.client.post(url)
        finally:
            # Make sure the transaction was rolled back.
            assert qs.count() == 0
            qs.all().delete()

    def test_get_requests_are_not_wrapped_in_a_transaction(self):
        self.endpoint(self._generate_view('GET'))
        qs = Addon.objects.filter(slug=self.slug)
        assert not qs.exists()
        url = reverse('test-dynamic-endpoint')
        try:
            with self.assertRaises(RuntimeError):
                self.client.get(url)
        finally:
            # Make sure the transaction wasn't rolled back.
            assert qs.count() == 1
            qs.all().delete()


class TestVersion(TestCase):

    def test_version_json(self):
        res = self.client.get('/__version__')
        assert res.status_code == 200
        assert res._headers['content-type'] == (
            'Content-Type', 'application/json')
        content = json.loads(force_text(res.content))
        assert content['python'] == '%s.%s' % (
            sys.version_info.major, sys.version_info.minor)
        assert content['django'] == '%s.%s' % (
            django.VERSION[0], django.VERSION[1])


class TestSiteStatusAPI(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('amo-site-status')

    def test_response(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data == {
            'read_only': False,
            'notice': None,
        }

        set_config('site_notice', 'THIS is NOT Á TEST!')
        with override_settings(READ_ONLY=True):
            response = self.client.get(self.url)
        assert response.data == {
            'read_only': True,
            'notice': 'THIS is NOT Á TEST!',
        }
