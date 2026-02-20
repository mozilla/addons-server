import json
import os
import re
import sys
from unittest import mock
from unittest.mock import patch
from urllib.parse import urlparse

import django
from django import test
from django.conf import settings
from django.test.client import Client, RequestFactory
from django.test.utils import override_settings
from django.urls import reverse

import pytest
from lxml import etree
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser, get_random_slug
from olympia.amo.sitemap import get_sitemap_path
from olympia.amo.tests import (
    APITestClientSessionID,
    TestCase,
    WithDynamicEndpointsAndTransactions,
    addon_factory,
    check_links,
    reverse_ns,
    user_factory,
)
from olympia.amo.views import handler500
from olympia.users.models import UserProfile
from olympia.zadmin.models import set_config


# Avoid database calls for this test as it's trying every lang in LANGUAGES
@patch('olympia.zadmin.models.get_config', lambda s: None)
@pytest.mark.parametrize('locale_pair', settings.LANGUAGES)
def test_locale_switcher(client, locale_pair):
    response = client.get(f'/{locale_pair[0]}/developers/')
    assert response.status_code == 200


class Test403(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='clouserw@gmail.com'))

    def test_403_no_app(self):
        response = self.client.get('/en-US/admin/', follow=True)
        assert response.status_code == 403
        self.assertTemplateUsed(response, 'amo/403.html')

    def test_403_app(self):
        response = self.client.get('/en-US/android/admin/', follow=True)
        assert response.status_code == 403
        self.assertTemplateUsed(response, 'amo/403.html')

    def test_403_api_services_api(self):
        response = self.client.get('/api/v5/services/403')
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == 'You do not have permission to perform this action.'


class Test404(TestCase):
    def test_404_no_app(self):
        """Make sure a 404 without an app doesn't turn into a 500."""
        # That could happen if helpers or templates expect APP to be defined.
        url = reverse('amo.services_monitor')
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

    def test_404_api_services_api(self):
        response = self.client.get('/api/v5/services/404')
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'

    def test_404_legacy_api(self):
        response = self.client.get('/en-US/firefox/api/1.0/search')
        assert response.status_code == 404
        self.assertTemplateNotUsed(response, 'amo/404.html')
        assert response['Cache-Control'] == 'max-age=172800'


class Test500(TestCase):
    def test_500_renders_correctly_with_no_queries_or_auth(self):
        with self.assertNumQueries(0):
            response = self.client.get('/services/500')
        assert response.status_code == 500
        self.assertTemplateUsed(response, 'amo/500.html')
        content = response.content.decode('utf-8')
        assert 'data-anonymous="true"' in content
        # We don't even want to show the log in link.
        assert 'Log in' not in content
        return content

    def test_500_renders_correctly_with_no_queries_or_auth_even_when_logged_in(self):
        # Being logged in shouldn't matter for the 500 page.
        user = user_factory()
        self.client.force_login(user)
        content = self.test_500_renders_correctly_with_no_queries_or_auth()
        assert user.email not in content

    def test_500_api(self):
        # Simulate an early API 500 not caught by DRF
        from olympia.api.middleware import APIRequestMiddleware

        request = RequestFactory().get('/api/v4/addons/addon/lol/')
        APIRequestMiddleware(lambda: None).process_exception(request, Exception())
        response = handler500(request)
        assert response.status_code == 500
        assert response['Content-Type'] == 'application/json'
        data = json.loads(response.content)
        assert data['detail'] == 'Internal Server Error'

    def test_500_api_services_api(self):
        response = self.client.get('/api/v5/services/500')
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
        super().setUp()
        self.url = reverse('devhub.addons')

    def test_tools_regular_user(self):
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url, follow=True)
        assert not response.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))

    def test_tools_developer(self):
        # Make them a developer.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.force_login(user)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        group = Group.objects.create(name='Staff', rules='Admin:Advanced')
        GroupUser.objects.create(group=group, user=user)

        response = self.client.get(self.url, follow=True)
        assert response.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))

    def test_tools_reviewer(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.url, follow=True)
        request = response.context['request']
        assert not request.user.is_developer
        assert acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))

    def test_tools_developer_and_reviewer(self):
        # Make them a developer.
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.force_login(user)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        response = self.client.get(self.url, follow=True)
        request = response.context['request']
        assert request.user.is_developer
        assert acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW)

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))

    def test_tools_admin(self):
        user = UserProfile.objects.get(email='admin@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.url, follow=True)
        assert response.status_code == 200
        request = response.context['request']
        assert not request.user.is_developer
        assert acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW)
        assert acl.action_allowed_for(request.user, amo.permissions.LOCALIZER)
        assert acl.action_allowed_for(request.user, amo.permissions.ANY_ADMIN)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('admin:index')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))

    def test_tools_developer_and_admin(self):
        # Make them a developer.
        user = UserProfile.objects.get(email='admin@mozilla.com')
        self.client.force_login(user)
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        response = self.client.get(self.url, follow=True)
        assert response.status_code == 200
        request = response.context['request']
        assert request.user.is_developer
        assert acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW)
        assert acl.action_allowed_for(request.user, amo.permissions.LOCALIZER)
        assert acl.action_allowed_for(request.user, amo.permissions.ANY_ADMIN)

        expected = [
            ('Tools', '#'),
            ('Manage My Submissions', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.submit.theme.agreement')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('admin:index')),
        ]
        check_links(expected, pq(response.content)('#aux-nav .tools a'))


class TestOtherStuff(TestCase):
    # Tests that don't need fixtures.
    def setUp(self):
        addon_factory(slug='foo')
        self.url = '/en-US/firefox/addon/foo/statistics/'

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#site-notice').length == 0

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#site-notice').length == 1

    def test_heading(self):
        response = self.client.get(self.url, follow=True)
        doc = pq(response.content)
        assert 'Firefox' == doc('.site-title img').attr('alt')
        assert 'Add-ons' == doc('.site-title').text()

    def test_login_link(self):
        response = self.client.get(self.url, follow=True)
        doc = pq(response.content)
        expected_link = (
            'http://testserver/api/v5/accounts/login/start/'
            '?to=%2Fen-US%2Ffirefox%2Faddon%2Ffoo%2Fstatistics%2F'
        )
        assert doc('.account.anonymous a')[1].attrib['href'] == expected_link

    def test_tools_loggedout(self):
        response = self.client.get(self.url, follow=True)
        assert pq(response.content)('#aux-nav .tools').length == 0

    def test_language_selector(self):
        doc = pq(test.Client().get(self.url).content)
        assert doc('form.languages option[selected]').attr('value') == 'en-us'

    def test_language_selector_variables(self):
        response = self.client.get(f'{self.url}?foo=fooval&bar=barval')
        doc = pq(response.content)('form.languages')

        assert doc('input[type=hidden][name=foo]').attr('value') == 'fooval'
        assert doc('input[type=hidden][name=bar]').attr('value') == 'barval'

    @override_settings(SECRET_CDN_TOKEN='foo')
    @patch.object(core, 'set_remote_addr')
    def test_remote_addr_from_cdn(self, set_remote_addr_mock):
        """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR correctly
        if request came from the CDN."""
        client = test.Client()
        # Send X-Forwarded-For and X-Request-Via-CDN as it shows up in a wsgi
        # request.
        client.get(
            '/en-US/developers/',
            follow=True,
            HTTP_X_FORWARDED_FOR='1.1.1.1,2.2.2.2',
            HTTP_X_REQUEST_VIA_CDN=settings.SECRET_CDN_TOKEN,
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


class TestHeartbeat(TestCase):
    def setUp(self):
        super().setUp()

        self.mocks = {}
        for check in [
            'memcache',
            'libraries',
            'elastic',
            'path',
            'database',
            'rabbitmq',
            'signer',
            'remotesettings',
            'cinder',
        ]:
            patcher = mock.patch(f'olympia.amo.monitors.{check}')
            self.mocks[check] = patcher.start()
            self.mocks[check].return_value = ('', None)
            self.addCleanup(patcher.stop)

    def test_front_heartbeat_success(self):
        response = self.client.get(reverse('amo.front_heartbeat'))
        assert response.status_code == 200

    def test_front_heartbeat_failure(self):
        self.mocks['database'].return_value = ('boom', None)

        response = self.client.get(reverse('amo.front_heartbeat'))

        assert response.status_code >= 500
        assert response.json()['database']['status'] == 'boom'

    @override_switch('dummy-monitor-fails', True)
    def test_front_heartbeat_dummy_monitor_no_failure(self):
        url = reverse('amo.front_heartbeat')
        response = self.client.get(url)

        assert response.status_code == 200

    def test_services_monitor_success(self):
        response = self.client.get(reverse('amo.services_monitor'))
        assert response.status_code == 200

    def test_services_monitor_failure(self):
        self.mocks['rabbitmq'].return_value = ('boom', None)

        response = self.client.get(reverse('amo.services_monitor'))

        assert response.status_code >= 500
        assert response.json()['rabbitmq']['status'] == 'boom'

    def test_services_monitor_dummy_monitor_failure(self):
        url = reverse('amo.services_monitor')
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTrue(response.json()['dummy_monitor']['state'])

        with override_switch('dummy-monitor-fails', True):
            response = self.client.get(url)

            assert response.status_code >= 500
            assert response.json()['dummy_monitor']['status'] == 'Dummy monitor failed'


class TestCORS(TestCase):
    fixtures = ('base/addon_3615',)

    def get(self, url, **headers):
        return self.client.get(url, HTTP_ORIGIN='testserver', **headers)

    def options(self, url, **headers):
        return self.client.options(url, HTTP_ORIGIN='somewhere', **headers)

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

    def test_cors_api_v5(self):
        url = reverse_ns('addon-detail', api_version='v4', args=(3615,))
        assert '/api/v4/' in url
        response = self.get(url)
        assert response.status_code == 200
        assert not response.has_header('Access-Control-Allow-Credentials')
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_cors_preflight(self):
        url = reverse_ns('addon-detail', args=(3615,))
        response = self.options(url)
        assert response.status_code == 200
        assert response['Access-Control-Allow-Origin'] == '*'
        assert sorted(response['Access-Control-Allow-Headers'].lower().split(', ')) == [
            'accept',
            'authorization',
            'content-type',
            'user-agent',
            'x-country-code',
            'x-csrftoken',
            'x-requested-with',
        ]

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
        id_url = f'{reverse("collections.list")}{settings.TASK_USER_ID}/'
        username_url = f'{reverse("collections.list")}mozilla/'
        response = self.client.get('/robots.txt')
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert f'Allow: {id_url}' in content
        assert f'Disallow: {id_url}$' in content
        assert f'Allow: {username_url}' in content
        assert f'Disallow: {username_url}$' in content


@pytest.mark.django_db
@override_settings(FXA_CONFIG={'default': {'client_id': ''}})
def test_fake_fxa_authorization_correct_values_passed():
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


@pytest.mark.django_db
@override_settings(FXA_CONFIG={'default': {'client_id': 'amodefault'}})
def test_fake_fxa_authorization_deactivated():
    url = reverse('fake-fxa-authorization')
    response = test.Client().get(url)
    assert response.status_code == 404


class TestAtomicRequests(WithDynamicEndpointsAndTransactions):
    def setUp(self):
        super().setUp()
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
        assert result.get('Access-Control-Allow-Origin') == '*'
        content = result.json()
        assert content['python'] == '{}.{}'.format(
            sys.version_info.major,
            sys.version_info.minor,
        )
        assert content['django'] == f'{django.VERSION[0]}.{django.VERSION[1]}'
        assert 'addons-linter' in content
        assert '.' in content['addons-linter']


class TestSiteStatusAPI(TestCase):
    client_class = APITestClientSessionID

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


@override_settings(ENV='dev')
def test_multipart_error():
    # We should throw a 400 because of the malformed multipart request and not
    # raise an exception. This ensures that we do with a fairly simple vie.
    client = Client()
    response = client.post(
        reverse('amo.client_info'),
        content_type='multipart/form-data',
        data='something wicked',
    )
    assert response.status_code == 400
    assert response.content == (
        b'\n<!doctype html>\n<html lang="en">\n<head>\n  '
        b'<title>Bad Request (400)</title>\n</head>\n<body>\n  '
        b'<h1>Bad Request (400)</h1><p></p>\n</body>\n</html>\n'
    )


@pytest.mark.django_db
def test_client_info():
    response = Client().get(reverse('amo.client_info'))
    assert response.status_code == 403

    with override_settings(ENV='dev'):
        response = Client().get(reverse('amo.client_info'))
        assert response.status_code == 200
        assert response.json() == {
            'HTTP_USER_AGENT': None,
            'HTTP_X_COUNTRY_CODE': None,
            'HTTP_X_FORWARDED_FOR': None,
            'REMOTE_ADDR': '127.0.0.1',
            'SERVER_NAME': 'testserver',
            'GET': {},
            'POST': {},
        }

        response = Client().get(
            reverse('amo.client_info'),
            data={'foo': 'bar'},
            HTTP_USER_AGENT='Foo/5.0',
            HTTP_X_FORWARDED_FOR='192.0.0.2,193.0.0.1',
            HTTP_X_COUNTRY_CODE='FR',
        )
        assert response.status_code == 200
        assert response.json() == {
            'HTTP_USER_AGENT': 'Foo/5.0',
            'HTTP_X_COUNTRY_CODE': 'FR',
            'HTTP_X_FORWARDED_FOR': '192.0.0.2,193.0.0.1',
            'REMOTE_ADDR': '127.0.0.1',
            'SERVER_NAME': 'testserver',
            'GET': {'foo': 'bar'},
            'POST': {},
        }

        response = Client().post(
            reverse('amo.client_info'),
            data={'foo': 'bar'},
            HTTP_USER_AGENT='Foo/5.0',
            HTTP_X_FORWARDED_FOR='192.0.0.2,193.0.0.1',
            HTTP_X_COUNTRY_CODE='FR',
        )
        assert response.status_code == 200
        assert response.json() == {
            'HTTP_USER_AGENT': 'Foo/5.0',
            'HTTP_X_COUNTRY_CODE': 'FR',
            'HTTP_X_FORWARDED_FOR': '192.0.0.2,193.0.0.1',
            'REMOTE_ADDR': '127.0.0.1',
            'SERVER_NAME': 'testserver',
            'GET': {},
            'POST': {'foo': 'bar'},
        }


@pytest.mark.django_db
def test_api_services():
    client = Client()

    response = client.get(reverse('v5:amo.client_info'))
    assert response.status_code == 403

    with override_settings(ENV='dev'):
        response = client.get(reverse('v5:amo.client_info'))
    assert response.status_code == 200


TEST_SITEMAPS_DIR = os.path.join(
    settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'sitemaps'
)


class TestSitemap(TestCase):
    @override_settings(SITEMAP_STORAGE_PATH=TEST_SITEMAPS_DIR)
    def test_index(self):
        result = self.client.get('/sitemap.xml')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result[settings.XSENDFILE_HEADER] == os.path.normpath(
            get_sitemap_path(None, None)
        )
        assert result.get('Cache-Control') == 'max-age=3600'

    @override_settings(SITEMAP_STORAGE_PATH=TEST_SITEMAPS_DIR)
    def test_section(self):
        result = self.client.get('/sitemap.xml?section=amo')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result[settings.XSENDFILE_HEADER] == os.path.normpath(
            get_sitemap_path('amo', None)
        )
        assert result.get('Cache-Control') == 'max-age=3600'

        # a section with more than one page
        result = self.client.get('/sitemap.xml?section=addons&app_name=firefox&p=2')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result[settings.XSENDFILE_HEADER] == os.path.normpath(
            get_sitemap_path('addons', 'firefox', 2)
        )
        assert result.get('Cache-Control') == 'max-age=3600'

        # and for android
        result = self.client.get('/sitemap.xml?section=addons&app_name=android')
        assert result.status_code == 200
        assert result.get('Content-Type') == 'application/xml'
        assert result[settings.XSENDFILE_HEADER] == os.path.normpath(
            get_sitemap_path('addons', 'android')
        )
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
        # ?debug should be ignored and the request treated as a nginx redirect
        assert result.content == b''
        assert result[settings.XSENDFILE_HEADER]

    @override_settings(SITEMAP_DEBUG_AVAILABLE=True)
    def test_debug_exceptions(self):
        # check that requesting an out of bounds page number 404s
        assert self.client.get('/sitemap.xml?debug&p=10').status_code == 404
        assert self.client.get('/sitemap.xml?debug&section=amo&p=10').status_code == 404
        # and a non-integer page number
        assert self.client.get('/sitemap.xml?debug&p=a').status_code == 404
        assert self.client.get('/sitemap.xml?debug&p=1.3').status_code == 404
        # invalid sections should also fail nicely
        assert self.client.get('/sitemap.xml?debug&section=foo').status_code == 404
        assert (
            self.client.get(
                '/sitemap.xml?debug&section=amo&app_name=firefox'
            ).status_code
            == 404
        )

    def test_exceptions(self):
        # check a non-integer page number
        assert self.client.get('/sitemap.xml?section=amo&p=a').status_code == 404
        assert self.client.get('/sitemap.xml?section=amo&p=1.3').status_code == 404
        # invalid sections should also fail nicely
        assert self.client.get('/sitemap.xml?section=foo').status_code == 404
        assert (
            self.client.get('/sitemap.xml?section=amo&app_name=firefox').status_code
            == 404
        )
