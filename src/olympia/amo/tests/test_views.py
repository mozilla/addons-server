# -*- coding: utf-8 -*-
import datetime
import json
import os
import re
import sys

from unittest import mock
from urllib.parse import urlparse

import django
from django import test
from django.conf import settings
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.http import http_date

import pytest

from lxml import etree
from unittest.mock import patch
from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser, get_random_slug
from olympia.amo.tests import (
    APITestClient,
    TestCase,
    WithDynamicEndpointsAndTransactions,
    check_links,
    reverse_ns,
    user_factory,
)
from olympia.amo.views import handler500
from olympia.users.models import UserProfile
from olympia.zadmin.models import set_config


@pytest.mark.django_db
@pytest.mark.parametrize('locale_pair', settings.LANGUAGES)
def test_locale_switcher(client, locale_pair):
    response = client.get('/{}/developers/'.format(locale_pair[0]))
    assert response.status_code == 200


class Test403(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(Test403, self).setUp()
        assert self.client.login(email='clouserw@gmail.com')

    def test_403_no_app(self):
        response = self.client.get('/en-US/admin/', follow=True)
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
        assert data['detail'] == 'Not found.'

    def test_404_api_v4(self):
        response = self.client.get('/api/v4/lol')
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'


class Test500(TestCase):
    def test_500_logged_in(self):
        self.client.login(email=user_factory().email)
        response = self.client.get('/services/500')
        assert response.status_code == 500
        self.assertTemplateUsed(response, 'amo/500.html')
        content = response.content.decode('utf-8')
        assert 'data-anonymous="false"' in content
        assert 'Log in' not in content

    def test_500_logged_out(self):
        response = self.client.get('/services/500')
        assert response.status_code == 500
        self.assertTemplateUsed(response, 'amo/500.html')
        content = response.content.decode('utf-8')
        assert 'data-anonymous="true"' in content
        assert 'Log in' in content

    def test_500_api(self):
        # Simulate an early API 500 not caught by DRF
        from olympia.api.middleware import APIRequestMiddleware

        request = RequestFactory().get('/api/v4/addons/addon/lol/')
        APIRequestMiddleware().process_exception(request, Exception())
        response = handler500(request)
        assert response.status_code == 500
        assert response['Content-Type'] == 'application/json'
        data = json.loads(response.content)
        assert data['detail'] == 'Internal Server Error'

    @override_settings(MIDDLEWARE=())
    def test_500_early_exception_no_middlewares(self):
        # Simulate a early 500 causing middlewares breakage - we should still
        # be able to display the 500.
        response = self.client.get('/services/500')
        assert response.status_code == 500
        self.assertTemplateUsed(response, 'amo/500.html')
        content = response.content.decode('utf-8')
        assert 'data-anonymous="true"' in content
        assert 'Log in' not in content  # No session, can't show login process.


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
        response = self.client.get(self.url, follow=True)
        assert not response.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)

    def test_tools_developer(self):
        # Make them a developer.
        user = self.login('regular', get=True)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        group = Group.objects.create(name='Staff', rules='Admin:Advanced')
        GroupUser.objects.create(group=group, user=user)

        response = self.client.get(self.url, follow=True)
        assert response.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)

    def test_tools_reviewer(self):
        self.login('reviewer')
        response = self.client.get(self.url, follow=True)
        request = response.context['request']
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
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)

    def test_tools_developer_and_reviewer(self):
        # Make them a developer.
        user = self.login('reviewer', get=True)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        response = self.client.get(self.url, follow=True)
        request = response.context['request']
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
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)

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
            ('Admin Tools', reverse('admin:index')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)

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
            ('Admin Tools', reverse('admin:index')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'), verify=False)


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

    @patch(
        'olympia.accounts.utils.default_fxa_login_url',
        lambda request: 'https://login.com',
    )
    def test_login_link(self):
        r = self.client.get(reverse('apps.appversions'), follow=True)
        doc = pq(r.content)
        assert 'https://login.com' == (doc('.account.anonymous a')[1].attrib['href'])

    def test_tools_loggedout(self):
        r = self.client.get(reverse('apps.appversions'), follow=True)
        assert pq(r.content)('#aux-nav .tools').length == 0

    def test_language_selector(self):
        doc = pq(test.Client().get('/en-US/firefox/pages/appversions/').content)
        assert doc('form.languages option[selected]').attr('value') == 'en-us'

    def test_language_selector_variables(self):
        r = self.client.get('/en-US/firefox/pages/appversions/?foo=fooval&bar=barval')
        doc = pq(r.content)('form.languages')

        assert doc('input[type=hidden][name=foo]').attr('value') == 'fooval'
        assert doc('input[type=hidden][name=bar]').attr('value') == 'barval'

    @patch.object(settings, 'KNOWN_PROXIES', ['127.0.0.1'])
    @patch.object(core, 'set_remote_addr')
    def test_remote_addr(self, set_remote_addr_mock):
        """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR."""
        client = test.Client()
        # Send X-Forwarded-For as it shows up in a wsgi request.
        client.get(
            '/en-US/developers/',
            follow=True,
            HTTP_X_FORWARDED_FOR='1.1.1.1',
            REMOTE_ADDR='127.0.0.1',
        )
        assert set_remote_addr_mock.call_count == 2
        assert set_remote_addr_mock.call_args_list[0] == (('1.1.1.1',), {})
        assert set_remote_addr_mock.call_args_list[1] == ((None,), {})

    def test_opensearch(self):
        client = test.Client()
        result = client.get('/en-US/firefox/opensearch.xml')

        assert result.get('Content-Type') == 'text/xml'

        doc = etree.fromstring(result.content)
        e = doc.find('{http://a9.com/-/spec/opensearch/1.1/}ShortName')
        assert e.text == 'Firefox Add-ons'


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
        assert (
            re.match(
                settings.CORS_URLS_REGEX,
                urlparse(reverse_ns('accounts.session')).path,
            )
            is None
        )


class TestContribute(TestCase):
    def test_contribute_json(self):
        result = self.client.get('/contribute.json')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/json'


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
        id_url = f"{reverse('collections.list')}{settings.TASK_USER_ID}/"
        username_url = f"{reverse('collections.list')}mozilla/"
        response = self.client.get('/robots.txt')
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert f'Allow: {id_url}' in content
        assert f'Disallow: {id_url}$' in content
        assert f'Allow: {username_url}' in content
        assert f'Disallow: {username_url}$' in content


def test_fake_fxa_authorization_correct_values_passed():
    with override_settings(DEBUG=True):  # USE_FAKE_FXA_AUTH is already True
        url = reverse('fake-fxa-authorization')
        response = test.Client().get(url, {'state': 'foobar'})
        assert response.status_code == 200
        doc = pq(response.content)
        form = doc('#fake_fxa_authorization')[0]
        assert form.attrib['action'] == reverse('auth:accounts.authenticate')
        elm = doc('#fake_fxa_authorization input[name=code]')[0]
        assert elm.attrib['value'] == 'fakecode'
        elm = doc('#fake_fxa_authorization input[name=state]')[0]
        assert elm.attrib['value'] == 'foobar'
        elm = doc('#fake_fxa_authorization input[name=fake_fxa_email]')
        assert elm  # No value yet, should just be present.


def test_fake_fxa_authorization_deactivated():
    url = reverse('fake-fxa-authorization')
    with override_settings(DEBUG=False, USE_FAKE_FXA_AUTH=False):
        response = test.Client().get(url)
    assert response.status_code == 404

    with override_settings(DEBUG=False, USE_FAKE_FXA_AUTH=True):
        response = test.Client().get(url)
    assert response.status_code == 404

    with override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=False):
        response = test.Client().get(url)
    assert response.status_code == 404


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
                'pretend this is an unhandled exception happening in a view.'
            )

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
        result = self.client.get('/__version__')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/json'
        content = result.json()
        assert content['python'] == '%s.%s' % (
            sys.version_info.major,
            sys.version_info.minor,
        )
        assert content['django'] == '%s.%s' % (django.VERSION[0], django.VERSION[1])


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


TEST_SITEMAPS_DIR = os.path.join(
    settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'sitemaps'
)


class TestSitemap(TestCase):
    @override_settings(SITEMAP_STORAGE_PATH=TEST_SITEMAPS_DIR)
    def test_index(self):
        result = self.client.get('/sitemap.xml')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert (
            b'<sitemap><loc>http://testserver/sitemap.xml?section=amo</loc>'
            in result.getvalue()
        )

    @override_settings(SITEMAP_STORAGE_PATH=TEST_SITEMAPS_DIR)
    def test_section(self):
        result = self.client.get('/sitemap.xml?section=amo')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert (
            b'<url><loc>http://testserver/en-US/about</loc><lastmod>2021-04-08<'
            in result.getvalue()
        )

        # a section with more than one page
        result = self.client.get('/sitemap.xml?section=addons&app_name=firefox&p=2')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert (
            b'<loc>http://testserver/en-US/firefox/addon/delicious-pierogi/</loc>'
            in result.getvalue()
        )

        # and for android
        result = self.client.get('/sitemap.xml?section=addons&app_name=android')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert (
            b'<loc>http://testserver/en-US/android/addon/delicious-pierogi/</loc>'
            in result.getvalue()
        )

    @override_settings(SITEMAP_STORAGE_PATH=TEST_SITEMAPS_DIR)
    def test_headers(self):
        file_timestamp = round(datetime.datetime.now().timestamp() - (60 * 60))

        def stat_side_effect(path):
            stat_list = list(os.stat(path))
            # patch the modified timestamp
            stat_list[8] = file_timestamp
            return os.stat_result(stat_list)

        with mock.patch('olympia.amo.views.os_stat') as stat_mock:
            stat_mock.side_effect = stat_side_effect
            result = self.client.get('/sitemap.xml')

        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result.get('Last-Modified') == http_date(file_timestamp)
        assert result.get('Expires') == http_date(file_timestamp + (24 * 60 * 60))
        assert not result.get('Cache-Control')

        # Repeat when the file is older than a day
        file_timestamp = file_timestamp - 24 * 60 * 60
        with mock.patch('olympia.amo.views.os_stat') as stat_mock:
            stat_mock.side_effect = stat_side_effect
            result = self.client.get('/sitemap.xml')

        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result.get('Last-Modified') == http_date(file_timestamp)
        assert not result.get('Expires')
        assert result.get('Cache-Control') == 'max-age=3600'

    @override_settings(SITEMAP_DEBUG_AVAILABLE=True)
    def test_debug_requests(self):
        # index
        result = self.client.get('/sitemap.xml?debug')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert (
            b'<sitemap><loc>http://testserver/sitemap.xml?section=amo</loc>'
            in result.content
        )

        # a section
        result = self.client.get('/sitemap.xml?section=addons&app_name=firefox&debug')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        # there aren't any addons so no content
        assert (
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            b'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n\n</urlset>'
            in result.content
        )

    @override_settings(SITEMAP_DEBUG_AVAILABLE=False)
    def test_debug_unavailable_on_prod(self):
        result = self.client.get('/sitemap.xml?debug')
        # it should 404 because debug is ignored andthe prebuilt sitemap.xml isn't there
        assert result.status_code == 404
