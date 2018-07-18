# -*- coding: utf-8 -*-
import json
import random

from datetime import datetime, timedelta

from django import test
from django.conf import settings
from django.test.testcases import TransactionTestCase
from django.test.utils import override_settings

import mock
import pytest

from lxml import etree
from mock import patch
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import (
    TestCase,
    WithDynamicEndpoints,
    check_links,
    reverse_ns,
)
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile


@pytest.mark.django_db
@pytest.mark.parametrize('locale', list(settings.LANGUAGES))
def test_locale_switcher(client, locale):
    response = client.get('/{}/firefox/'.format(locale))
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
        response = self.client.get('/en-US/thunderbird/admin/', follow=True)
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
        res = self.client.get('/en-US/thunderbird/xxxxxxx')
        assert res.status_code == 404
        self.assertTemplateUsed(res, 'amo/404.html')
        links = pq(res.content)('[role=main] ul a[href^="/en-US/thunderbird"]')
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
    fixtures = ('base/users', 'base/global-stats', 'base/addon_3615')

    def setUp(self):
        super(TestCommon, self).setUp()
        self.url = reverse('home')

    def login(self, user=None, get=False):
        email = '%s@mozilla.com' % user
        super(TestCommon, self).login(email)
        if get:
            return UserProfile.objects.get(email=email)

    @override_switch('disable-lwt-uploads', active=False)
    def test_tools_regular_user_lwt_enabled(self):
        self.login('regular')
        r = self.client.get(self.url, follow=True)
        assert not r.context['request'].user.is_developer

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.agreement')),
            ('Submit a New Theme', reverse('devhub.themes.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'), verify=False)

    @override_switch('disable-lwt-uploads', active=True)
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
            ('Submit a New Theme', reverse('devhub.themes.submit')),
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
            ('Submit a New Theme', reverse('devhub.themes.submit')),
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
            ('Submit a New Theme', reverse('devhub.themes.submit')),
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
            ('Submit a New Theme', reverse('devhub.themes.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('zadmin.index')),
        ]
        check_links(
            expected, pq(response.content)('#aux-nav .tools a'), verify=False
        )

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
            ('Submit a New Theme', reverse('devhub.themes.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Manage API Keys', reverse('devhub.api_key')),
            ('Reviewer Tools', reverse('reviewers.dashboard')),
            ('Admin Tools', reverse('zadmin.index')),
        ]
        check_links(
            expected, pq(response.content)('#aux-nav .tools a'), verify=False
        )


class TestOtherStuff(TestCase):
    # Tests that don't need fixtures but do need redis mocked.

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get('/en-US/firefox/')
        doc = pq(response.content)
        assert doc('#site-notice').length == 0
        assert doc('#site-nonfx').length == 1
        assert doc('#site-welcome').length == 1

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get('/en-US/firefox/')
        doc = pq(response.content)
        assert doc('#site-notice').length == 1
        assert doc('#site-nonfx').length == 1
        assert doc('#site-welcome').length == 1

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_thunderbird_balloons_no_readonly(self):
        response = self.client.get('/en-US/thunderbird/')
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#site-notice').length == 0

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_thunderbird_balloons_readonly(self):
        response = self.client.get('/en-US/thunderbird/')
        doc = pq(response.content)
        assert doc('#site-notice').length == 1
        assert (
            doc('#site-nonfx').length == 0
        ), 'This balloon should appear for Firefox only'
        assert doc('#site-welcome').length == 1

    def test_heading(self):
        def title_eq(url, alt, text):
            response = self.client.get(url, follow=True)
            doc = pq(response.content)
            assert alt == doc('.site-title img').attr('alt')
            assert text == doc('.site-title').text()

        title_eq('/firefox/', 'Firefox', 'Add-ons')
        title_eq('/thunderbird/', 'Thunderbird', 'Add-ons')
        title_eq('/android/', 'Firefox for Android', 'Android Add-ons')

    @patch(
        'olympia.accounts.utils.default_fxa_login_url',
        lambda request: 'https://login.com',
    )
    def test_login_link(self):
        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        assert 'https://login.com' == (
            doc('.account.anonymous a')[1].attrib['href']
        )

    def test_tools_loggedout(self):
        r = self.client.get(reverse('home'), follow=True)
        assert pq(r.content)('#aux-nav .tools').length == 0

    def test_language_selector(self):
        doc = pq(test.Client().get('/en-US/firefox/').content)
        assert doc('form.languages option[selected]').attr('value') == 'en-us'

    def test_language_selector_variables(self):
        r = self.client.get('/en-US/firefox/?foo=fooval&bar=barval')
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
            '/en-US/firefox/',
            follow=True,
            HTTP_X_FORWARDED_FOR='1.1.1.1',
            REMOTE_ADDR='127.0.0.1',
        )
        assert set_remote_addr_mock.call_count == 2
        assert set_remote_addr_mock.call_args_list[0] == (('1.1.1.1',), {})
        assert set_remote_addr_mock.call_args_list[1] == ((None,), {})

    @patch.object(settings, 'CDN_HOST', 'https://cdn.example.com')
    def test_jsi18n_caching_and_cdn(self):
        # The jsi18n catalog should be cached for a long time.
        # Get the url from a real page so it includes the build id.
        client = test.Client()
        doc = pq(client.get('/', follow=True).content)
        js_url = '%s%s' % (settings.CDN_HOST, reverse('jsi18n'))
        url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

        response = client.get(
            url_with_build.replace(settings.CDN_HOST, ''), follow=False
        )
        self.assertCloseToNow(
            response['Expires'], now=datetime.now() + timedelta(days=365)
        )

    @pytest.mark.needs_locales_compilation
    def test_jsi18n(self):
        """Test that the jsi18n library has an actual catalog of translations
        rather than just identity functions."""

        en = self.client.get(reverse('jsi18n')).content

        with self.activate('fr'):
            fr = self.client.get(reverse('jsi18n')).content

        assert en != fr

        for content in (en, fr):
            assert 'django.catalog = ' in content
            assert '/* gettext identity library */' not in content

    def test_dictionaries_link(self):
        doc = pq(test.Client().get('/', follow=True).content)
        assert doc('#site-nav #more .more-lang a').attr('href') == (
            reverse('browse.language-tools')
        )

    def test_mobile_link_firefox(self):
        doc = pq(test.Client().get('/firefox', follow=True).content)
        assert doc('#site-nav #more .more-mobile a').length == 1

    def test_mobile_link_nonfirefox(self):
        for app in ('thunderbird', 'android'):
            doc = pq(test.Client().get('/' + app, follow=True).content)
            assert doc('#site-nav #more .more-mobile').length == 0

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
        response = self.get(reverse('home'))
        assert response.status_code == 200
        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Allow-Credentials')

    def test_no_cors_legacy_api(self):
        response = self.get('/en-US/firefox/api/1.5/search/test')
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


class TestContribute(TestCase):
    def test_contribute_json(self):
        res = self.client.get('/contribute.json')
        assert res.status_code == 200
        assert res._headers['content-type'] == (
            'Content-Type',
            'application/json',
        )


class TestRobots(TestCase):
    @override_settings(ENGAGE_ROBOTS=True)
    def test_disable_collections(self):
        """Make sure /en-US/firefox/collections/ gets disabled"""
        url = reverse('collections.list')
        response = self.client.get('/robots.txt')
        assert response.status_code == 200
        assert 'Disallow: %s' % url in response.content


class TestAtomicRequests(WithDynamicEndpoints, TransactionTestCase):
    def setUp(self):
        super(TestAtomicRequests, self).setUp()
        self.slug = 'slug-{}'.format(random.randint(1, 1000))
        self.endpoint(self.view)

    def view(self, request):
        Addon.objects.create(slug=self.slug)
        raise RuntimeError(
            'pretend this is an error that would roll back the transaction'
        )

    def test_exception_rolls_back_transaction(self):
        qs = Addon.objects.filter(slug=self.slug)
        try:
            with self.assertRaises(RuntimeError):
                self.client.get('/dynamic-endpoint', follow=True)
            # Make sure the transaction was rolled back.
            assert qs.count() == 0
        finally:
            qs.all().delete()


class TestVersion(TestCase):
    def test_version_json(self):
        res = self.client.get('/__version__')
        assert res.status_code == 200
        assert res._headers['content-type'] == (
            'Content-Type',
            'application/json',
        )
