# -*- coding: utf-8 -*-
from datetime import datetime
import urllib

from django import test
from django.conf import settings

import commonware.log
from lxml import etree
import mock
from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from access import acl
from addons.models import Addon, AddonUser
from amo.helpers import locale_url, urlparams
from amo.pyquery_wrapper import PyQuery
from amo.tests import check_links
from amo.urlresolvers import reverse
from users.models import UserProfile


class Test404(amo.tests.TestCase):

    def test_404_no_app(self):
        """Make sure a 404 without an app doesn't turn into a 500."""
        # That could happen if helpers or templates expect APP to be defined.
        url = reverse('amo.monitor')
        response = self.client.get(url + 'nonsense')
        eq_(response.status_code, 404)
        self.assertTemplateUsed(response, 'amo/404.html')

    def test_404_app_links(self):
        response = self.client.get('/en-US/thunderbird/xxxxxxx')
        eq_(response.status_code, 404)
        self.assertTemplateUsed(response, 'amo/404.html')
        links = pq(response.content)('[role=main] ul li a:not([href^=mailto])')
        eq_(len(links), 4)
        for link in links:
            href = link.attrib['href']
            assert href.startswith('/en-US/thunderbird'), href


class TestCommon(amo.tests.TestCase):
    fixtures = ('base/users', 'base/global-stats', 'base/configs',
                'base/addon_3615')

    def setUp(self):
        self.url = reverse('home')
        # TODO: Remove when `accept-webapps` flag is gone.
        self.patcher = mock.patch('waffle.flag_is_active')
        self.patcher.start().return_value = True
        self.addCleanup(self.patcher.stop)

    def login(self, user):
        user = UserProfile.objects.get(email='%s@mozilla.com' % user)
        self.client.login(username=user.email, password='password')
        return user

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get('/en-US/firefox/')
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 0)
        eq_(doc('#site-nonfx').length, 1)
        eq_(doc('#site-welcome').length, 1)
        eq_(doc('#site-noinstall-apps').length, 0)
        eq_(doc('#acr-pitch').length, 1)

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get('/en-US/firefox/')
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 1)
        eq_(doc('#site-nonfx').length, 1)
        eq_(doc('#site-welcome').length, 1)
        eq_(doc('#site-noinstall-apps').length, 0)
        eq_(doc('#acr-pitch').length, 1)

    @mock.patch.object(settings, 'READ_ONLY', False)
    def test_thunderbird_balloons_no_readonly(self):
        response = self.client.get('/en-US/thunderbird/')
        eq_(response.status_code, 200)
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 0)

    @mock.patch.object(settings, 'READ_ONLY', True)
    def test_thunderbird_balloons_readonly(self):
        response = self.client.get('/en-US/thunderbird/')
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 1)
        eq_(doc('#site-nonfx').length, 0,
            'This balloon should appear for Firefox only')
        eq_(doc('#acr-pitch').length, 0,
            'This balloon should appear for Firefox only')
        eq_(doc('#site-welcome').length, 1)
        eq_(doc('#site-noinstall-apps').length, 0)

    def test_tools_loggedout(self):
        r = self.client.get(self.url, follow=True)
        eq_(pq(r.content)('#aux-nav .tools').length, 0)

    def test_tools_regular_user(self):
        self.login('regular')
        r = self.client.get(self.url, follow=True)
        eq_(r.context['request'].amo_user.is_developer, False)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_tools_developer(self):
        # Make them a developer.
        user = self.login('regular')
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        r = self.client.get(self.url, follow=True)
        eq_(r.context['request'].amo_user.is_developer, True)

        expected = [
            ('Tools', '#'),
            ('Manage My Add-ons', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Manage My Apps', reverse('devhub.apps')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_tools_editor(self):
        self.login('editor')
        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        eq_(request.amo_user.is_developer, False)
        eq_(acl.action_allowed(request, 'Addons', 'Review'), True)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Editor Tools', reverse('editors.home')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_tools_developer_and_editor(self):
        # Make them a developer.
        user = self.login('editor')
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        eq_(request.amo_user.is_developer, True)
        eq_(acl.action_allowed(request, 'Addons', 'Review'), True)

        expected = [
            ('Tools', '#'),
            ('Manage My Add-ons', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Manage My Apps', reverse('devhub.apps')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Editor Tools', reverse('editors.home')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_tools_admin(self):
        self.login('admin')
        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        eq_(request.amo_user.is_developer, False)
        eq_(acl.action_allowed(request, 'Addons', 'Review'), True)
        eq_(acl.action_allowed(request, 'Localizer', '%'), True)
        eq_(acl.action_allowed(request, 'Admin', '%'), True)

        expected = [
            ('Tools', '#'),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Editor Tools', reverse('editors.home')),
            ('Localizer Tools', '/localizers'),
            ('Admin Tools', reverse('zadmin.home')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_tools_developer_and_admin(self):
        # Make them a developer.
        user = self.login('admin')
        AddonUser.objects.create(user=user, addon=Addon.objects.all()[0])

        r = self.client.get(self.url, follow=True)
        request = r.context['request']
        eq_(request.amo_user.is_developer, True)
        eq_(acl.action_allowed(request, 'Addons', 'Review'), True)
        eq_(acl.action_allowed(request, 'Localizer', '%'), True)
        eq_(acl.action_allowed(request, 'Admin', '%'), True)

        expected = [
            ('Tools', '#'),
            ('Manage My Add-ons', reverse('devhub.addons')),
            ('Submit a New Add-on', reverse('devhub.submit.1')),
            ('Manage My Apps', reverse('devhub.apps')),
            ('Submit a New App', reverse('devhub.submit_apps.1')),
            ('Submit a New Persona', reverse('devhub.personas.submit')),
            ('Developer Hub', reverse('devhub.index')),
            ('Editor Tools', reverse('editors.home')),
            ('Localizer Tools', '/localizers'),
            ('Admin Tools', reverse('zadmin.home')),
        ]
        check_links(expected, pq(r.content)('#aux-nav .tools a'))

    def test_heading(self):
        def title_eq(url, alt, text):
            response = self.client.get(url, follow=True)
            doc = PyQuery(response.content)
            eq_(alt, doc('.site-title img').attr('alt'))
            eq_(text, doc('.site-title').text())

        title_eq('/firefox', 'Firefox', 'Add-ons')
        title_eq('/thunderbird', 'Thunderbird', 'Add-ons')
        title_eq('/mobile', 'Mobile', 'Mobile Add-ons')
        title_eq('/android', 'Android', 'Android Add-ons')

    def test_xenophobia(self):
        r = self.client.get(self.url, follow=True)
        self.assertNotContains(r, 'show only English (US) add-ons')

    def test_login_link(self):
        r = self.client.get(self.url, follow=True)
        doc = PyQuery(r.content)
        next = urllib.urlencode({'to': '/en-US/firefox/'})
        eq_('/en-US/firefox/users/login?%s' % next,
            doc('.account.anonymous a')[1].attrib['href'])


class TestOtherStuff(amo.tests.TestCase):
    # Tests that don't need fixtures but do need redis mocked.

    def test_language_selector(self):
        doc = pq(test.Client().get('/en-US/firefox/').content)
        eq_(doc('form.languages option[selected]').attr('value'), 'en-us')

    def test_language_selector_variables(self):
        r = self.client.get('/en-US/firefox/?foo=fooval&bar=barval')
        doc = pq(r.content)('form.languages')

        eq_(doc('input[type=hidden][name=foo]').attr('value'), 'fooval')
        eq_(doc('input[type=hidden][name=bar]').attr('value'), 'barval')

    @patch.object(settings, 'KNOWN_PROXIES', ['127.0.0.1'])
    def test_remote_addr(self):
        """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR."""
        client = test.Client()
        # Send X-Forwarded-For as it shows up in a wsgi request.
        client.get('/en-US/firefox/', follow=True,
                   HTTP_X_FORWARDED_FOR='1.1.1.1')
        eq_(commonware.log.get_remote_addr(), '1.1.1.1')

    def test_jsi18n_caching(self):
        # The jsi18n catalog should be cached for a long time.
        # Get the url from a real page so it includes the build id.
        client = test.Client()
        doc = pq(client.get('/', follow=True).content)
        js_url = reverse('jsi18n')
        url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

        response = client.get(url_with_build, follow=True)
        fmt = '%a, %d %b %Y %H:%M:%S GMT'
        expires = datetime.strptime(response['Expires'], fmt)
        assert (expires - datetime.now()).days >= 365

    def test_dictionaries_link(self):
        doc = pq(test.Client().get('/', follow=True).content)
        eq_(doc('#site-nav #more .more-lang a').attr('href'),
            reverse('browse.language-tools'))

    def test_personas_subnav(self):
        doc = pq(self.client.get(reverse('home')).content)
        base_url = reverse('browse.personas')
        expected = [
            ('Personas', base_url),
            ('Most Popular', urlparams(base_url, sort='popular')),
            ('Top Rated', urlparams(base_url, sort='rating')),
            ('Newest', urlparams(base_url, sort='created')),
        ]
        check_links(expected, doc('#site-nav #personas a'))

    def test_mobile_link_firefox(self):
        doc = pq(test.Client().get('/firefox', follow=True).content)
        eq_(doc('#site-nav #more .more-mobile a').attr('href'),
            locale_url(amo.MOBILE.short))

    def test_mobile_link_nonfirefox(self):
        for app in ('thunderbird', 'mobile'):
            doc = pq(test.Client().get('/' + app, follow=True).content)
            eq_(doc('#site-nav #more .more-mobile').length, 0)

    def test_opensearch(self):
        client = test.Client()
        page = client.get('/en-US/firefox/opensearch.xml')

        wanted = ('Content-Type', 'text/xml')
        eq_(page._headers['content-type'], wanted)

        doc = etree.fromstring(page.content)
        e = doc.find("{http://a9.com/-/spec/opensearch/1.1/}ShortName")
        eq_(e.text, "Firefox Add-ons")

    def test_login_link(self):
        # Test that the login link encodes parameters correctly.
        r = test.Client().get('/?your=mom', follow=True)
        doc = pq(r.content)
        assert doc('.account.anonymous a')[1].attrib['href'].endswith(
                '?to=%2Fen-US%2Ffirefox%2F%3Fyour%3Dmom'), ("Got %s" %
                doc('.account.anonymous a')[1].attrib['href'])

        r = test.Client().get(u'/ar/firefox/?q=འ')
        doc = pq(r.content)
        link = doc('.account.anonymous a')[1].attrib['href']
        assert link.endswith('?to=%2Far%2Ffirefox%2F%3Fq%3D%25E0%25BD%25A0')

    @mock.patch.object(settings, 'PFS_URL', 'https://pfs.mozilla.org/pfs.py')
    def test_plugincheck_redirect(self):
        r = test.Client().get('/services/pfs.php?'
                              'mimetype=application%2Fx-shockwave-flash&'
                              'appID={ec8030f7-c20a-464f-9b0e-13a3a9e97384}&'
                              'appVersion=20120215223356&'
                              'clientOS=Windows%20NT%205.1&'
                              'chromeLocale=en-US&appRelease=10.0.2')
        self.assertEquals(r.status_code, 302)
        self.assertEquals(r['Location'], ('https://pfs.mozilla.org/pfs.py?'
                          'mimetype=application%2Fx-shockwave-flash&'
                          'appID=%7Bec8030f7-c20a-464f-9b0e-13a3a9e97384%7D&'
                          'appVersion=20120215223356&'
                          'clientOS=Windows%20NT%205.1&'
                          'chromeLocale=en-US&appRelease=10.0.2'))
