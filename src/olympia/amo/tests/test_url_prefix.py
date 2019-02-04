from django import shortcuts
from django.conf import settings
from django.urls import set_script_prefix
from django.test.client import Client, RequestFactory

import pytest

from olympia.amo import urlresolvers
from olympia.amo.middleware import LocaleAndAppURLMiddleware
from olympia.amo.tests import BaseTestCase, TestCase


pytestmark = pytest.mark.django_db


class MiddlewareTest(BaseTestCase):
    """Tests that the locale and app redirection work properly."""

    def setUp(self):
        super(MiddlewareTest, self).setUp()
        self.rf = RequestFactory()
        self.middleware = LocaleAndAppURLMiddleware()

    def test_redirection(self):
        redirections = {
            '/': '/en-US/firefox/',
            '/en-US': '/en-US/firefox/',
            '/firefox': '/en-US/firefox/',
            '/android': '/en-US/android/',

            # Make sure we don't mess with trailing slashes.
            '/addon/1/': '/en-US/firefox/addon/1/',
            '/addon/1': '/en-US/firefox/addon/1',

            # Check an invalid locale.
            '/sda/firefox/addon/1': '/en-US/firefox/addon/1',

            # Check a consolidated language (e.g. es-* -> es).
            '/es-ES/firefox/addon/1': '/es/firefox/addon/1',
            '/es-PE/firefox/addon/1': '/es/firefox/addon/1',

            # /developers doesn't get an app.
            '/developers': '/en-US/developers',

            # Check basic use-cases with a 'lang' GET parameter:
            '/?lang=fr': '/fr/firefox/',
            '/addon/1/?lang=fr': '/fr/firefox/addon/1/',
            '/addon/1?lang=fr': '/fr/firefox/addon/1',
            '/firefox?lang=fr': '/fr/firefox/',
            '/developers?lang=fr': '/fr/developers',
        }

        for path, location in redirections.items():
            response = self.middleware.process_request(self.rf.get(path))
            assert response.status_code == 301
            assert response['Location'] == location

    def process(self, *args, **kwargs):
        self.request = self.rf.get(*args, **kwargs)
        return self.middleware.process_request(self.request)

    def test_no_redirect(self):
        # /services doesn't get an app or locale.
        response = self.process('/services')
        assert response is None

        # Things matching settings.SUPPORTED_NONAPPS_NONLOCALES_REGEX don't get
        # a redirect either, even if they have a lang GET parameter.
        with self.settings(SUPPORTED_NONAPPS_NONLOCALES_REGEX=r'^lol'):
            response = self.process('/lol?lang=fr')
            assert self.request.LANG == 'fr'
            assert response is None

            response = self.process('/lol')
            assert self.request.LANG == 'en-US'
            assert response is None

    def test_v3_api_no_redirect(self):
        response = self.process('/api/v3/some/endpoint/')
        assert response is None
        response = self.process('/api/v4/some/endpoint/')
        assert response is None

    def test_v1_api_is_identified_as_api_request(self):
        response = self.process('/en-US/firefox/api/')
        assert response is None
        assert self.request.LANG == 'en-US'
        assert self.request.is_legacy_api

        # double-check _only_ /api/ is marked as .is_api
        response = self.process('/en-US/firefox/apii/')
        assert response is None
        assert self.request.LANG == 'en-US'
        assert not self.request.is_legacy_api

    def test_vary(self):
        response = self.process('/')
        assert response['Vary'] == 'Accept-Language, User-Agent'

        response = self.process('/firefox')
        assert response['Vary'] == 'Accept-Language'

        response = self.process('/en-US')
        assert response['Vary'] == 'User-Agent'

        response = self.process('/en-US/thunderbird')
        assert 'Vary' not in response

    def test_no_redirect_with_script(self):
        response = self.process('/services', SCRIPT_NAME='/oremj')
        assert response is None

    def test_get_app(self):
        def check(url, expected, ua):
            response = self.process(url, HTTP_USER_AGENT=ua)
            assert response['Location'] == expected

        check('/en-US/', '/en-US/firefox/', 'Firefox')

        # SeaMonkey gets priority because it has both strings in its UA...
        check('/en-US/', '/en-US/seamonkey/', 'Firefox SeaMonkey')

        # Android can found by its user agent.
        check('/en-US/', '/en-US/android/', 'Fennec/12.0.1')
        check('/en-US/', '/en-US/android/', 'Fennec/12')
        check('/en-US/', '/en-US/android/', 'Fennec/11.0')

        # And the user agent changed again.
        check('/en-US/', '/en-US/android/',
              'Mozilla/5.0 (Android; Mobile; rv:17.0) Gecko/17.0 Firefox/17.0')

        # And the user agent yet changed again.
        check('/en-US/', '/en-US/android/',
              'Mozilla/5.0 (Mobile; rv:18.0) Gecko/18.0 Firefox/18.0')

        # And the tablet user agent yet changed again!
        check('/en-US/', '/en-US/android/',
              'Mozilla/5.0 (Android; Tablet; rv:18.0) Gecko/18.0 Firefox/18.0')

    def test_get_lang(self):
        def check(url, expected):
            response = self.process(url)
            self.assertUrlEqual(response['Location'], expected)

        check('/services?lang=fr', '/services')
        check('/en-US/firefox?lang=fr', '/fr/firefox/')
        check('/de/admin/?lang=fr&foo=bar', '/fr/admin/?foo=bar')
        check('/en-US/firefox/?lang=fake', '/en-US/firefox/')
        check('/firefox/?lang=fr', '/fr/firefox/')
        check('/firefox/?lang=fake', '/en-US/firefox/')
        check('/en-US/extensions/?foo=fooval&bar=barval&lang=fr',
              '/fr/firefox/extensions/?foo=fooval&bar=barval')
        check('/en-US/firefox?lang=es-PE', '/es/firefox/')


class TestPrefixer(BaseTestCase):

    def tearDown(self):
        urlresolvers.clean_url_prefixes()
        set_script_prefix('/')
        super(TestPrefixer, self).tearDown()

    def test_split_path(self):

        def split_eq(url, locale, app, path):
            rf = RequestFactory()
            prefixer = urlresolvers.Prefixer(rf.get(url))
            actual = (prefixer.locale, prefixer.app, prefixer.shortened_path)
            assert actual == (locale, app, path)

        split_eq('/', '', '', '')
        split_eq('/en-US', 'en-US', '', '')
        split_eq('/en-US/firefox', 'en-US', 'firefox', '')
        split_eq('/en-US/firefox/', 'en-US', 'firefox', '')
        split_eq('/en-US/firefox/foo', 'en-US', 'firefox', 'foo')
        split_eq('/en-US/firefox/foo/', 'en-US', 'firefox', 'foo/')
        split_eq('/en-US/foo', 'en-US', '', 'foo')
        split_eq('/en-US/foo/', 'en-US', '', 'foo/')
        split_eq('/bad/firefox/foo', '', 'firefox', 'foo')
        split_eq('/bad/firefox/foo/', '', 'firefox', 'foo/')
        split_eq('/firefox/foo', '', 'firefox', 'foo')
        split_eq('/firefox/foo/', '', 'firefox', 'foo/')
        split_eq('/foo', '', '', 'foo')
        split_eq('/foo/', '', '', 'foo/')

    def test_fix(self):
        rf = RequestFactory()
        prefixer = urlresolvers.Prefixer(rf.get('/'))

        assert prefixer.fix('/') == '/en-US/firefox/'
        assert prefixer.fix('/foo') == '/en-US/firefox/foo'
        assert prefixer.fix('/foo/') == '/en-US/firefox/foo/'
        assert prefixer.fix('/admin') == '/en-US/admin'
        assert prefixer.fix('/admin/') == '/en-US/admin/'

        prefixer.locale = 'de'
        prefixer.app = 'thunderbird'

        assert prefixer.fix('/') == '/de/thunderbird/'
        assert prefixer.fix('/foo') == '/de/thunderbird/foo'
        assert prefixer.fix('/foo/') == '/de/thunderbird/foo/'
        assert prefixer.fix('/admin') == '/de/admin'
        assert prefixer.fix('/admin/') == '/de/admin/'

    def test_reverse(self):
        # Make sure it works outside the request.
        urlresolvers.clean_url_prefixes()  # Modified in BaseTestCase.
        assert urlresolvers.reverse('home') == '/'

        # With a request, locale and app prefixes work.
        Client().get('/')
        assert urlresolvers.reverse('home') == '/en-US/firefox/'

    def test_resolve(self):
        func, args, kwargs = urlresolvers.resolve('/')
        assert func.__name__ == 'home'

        # With a request with locale and app prefixes, it still works.
        Client().get('/')
        func, args, kwargs = urlresolvers.resolve('/en-US/firefox/')
        assert func.__name__ == 'home'

    def test_script_name(self):
        rf = RequestFactory()
        request = rf.get('/foo', SCRIPT_NAME='/oremj')
        prefixer = urlresolvers.Prefixer(request)
        assert prefixer.fix(prefixer.shortened_path) == (
            '/oremj/en-US/firefox/foo')

        # Now check reverse.
        urlresolvers.set_url_prefix(prefixer)
        assert urlresolvers.reverse('home') == '/oremj/en-US/firefox/'


class TestPrefixerActivate(TestCase):

    def test_activate_locale(self):
        with self.activate(locale='fr'):
            assert urlresolvers.reverse('home') == '/fr/firefox/'
        assert urlresolvers.reverse('home') == '/en-US/firefox/'

    def test_activate_app(self):
        with self.activate(app='android'):
            assert urlresolvers.reverse('home') == '/en-US/android/'
        assert urlresolvers.reverse('home') == '/en-US/firefox/'

    def test_activate_app_locale(self):
        with self.activate(locale='de', app='thunderbird'):
            assert urlresolvers.reverse('home') == '/de/thunderbird/'
        assert urlresolvers.reverse('home') == '/en-US/firefox/'


def test_redirect():
    """Make sure django.shortcuts.redirect uses our reverse."""
    Client().get('/')
    redirect = shortcuts.redirect('home')
    assert redirect['Location'] == '/en-US/firefox/'


def test_outgoing_url():
    redirect_url = settings.REDIRECT_URL
    secretkey = settings.REDIRECT_SECRET_KEY
    exceptions = settings.REDIRECT_URL_ALLOW_LIST
    settings.REDIRECT_URL = 'http://example.net'
    settings.REDIRECT_SECRET_KEY = 'sekrit'
    settings.REDIRECT_URL_ALLOW_LIST = ['nicedomain.com']

    try:
        myurl = 'http://example.com'
        s = urlresolvers.get_outgoing_url(myurl)

        # Regular URLs must be escaped.
        assert s == (
            'http://example.net/bc7d4bb262c9f0b0f6d3412ede7d3252c2e311bb1d55f6'
            '2315f636cb8a70913b/'
            'http%3A//example.com')

        # No double-escaping of outgoing URLs.
        s2 = urlresolvers.get_outgoing_url(s)
        assert s == s2

        evil = settings.REDIRECT_URL.rstrip('/') + '.evildomain.com'
        s = urlresolvers.get_outgoing_url(evil)
        assert s != evil  # 'No subdomain abuse of double-escaping protection.'

        nice = 'http://nicedomain.com/lets/go/go/go'
        assert nice == urlresolvers.get_outgoing_url(nice)

    finally:
        settings.REDIRECT_URL = redirect_url
        settings.REDIRECT_SECRET_KEY = secretkey
        settings.REDIRECT_URL_ALLOW_LIST = exceptions


def test_outgoing_url_dirty_unicode():
    bad = (u'http://chupakabr.ru/\u043f\u0440\u043e\u0435\u043a\u0442\u044b/'
           u'\u043c\u0443\u0437\u044b\u043a\u0430-vkontakteru/')
    urlresolvers.get_outgoing_url(bad)  # bug 564057


def test_outgoing_url_query_params():
    url = 'http://xx.com?q=1&v=2'
    fixed = urlresolvers.get_outgoing_url(url)
    assert fixed.endswith('http%3A//xx.com%3Fq=1&v=2'), fixed

    url = 'http://xx.com?q=1&amp;v=2'
    fixed = urlresolvers.get_outgoing_url(url)
    assert fixed.endswith('http%3A//xx.com%3Fq=1&v=2'), fixed

    # Check XSS vectors.
    url = 'http://xx.com?q=1&amp;v=2" style="123"'
    fixed = urlresolvers.get_outgoing_url(url)
    assert fixed.endswith('%3A//xx.com%3Fq=1&v=2%22%20style=%22123%22'), fixed


def test_outgoing_url_javascript_scheme():
    url = 'javascript://addons.mozilla.org/%0Aalert(location.href)'
    fixed = urlresolvers.get_outgoing_url(url)
    assert fixed == '/'


@pytest.mark.parametrize("test_input,expected", [
    ('ga-ie', 'ga-IE'),
    # Capitalization is no big deal.
    ('ga-IE', 'ga-IE'),
    ('GA-ie', 'ga-IE'),
    # Go for something less specific.
    ('fr-FR', 'fr'),
    # Go for something more specific.
    ('ga', 'ga-IE'),
    ('ga-XX', 'ga-IE'),
    # With multiple zh-XX choices, choose the first alphabetically.
    ('zh', 'zh-CN'),
    # Default to en-us.
    ('xx', 'en-US'),
    # Check q= sorting.
    ('fr,en;q=0.8', 'fr'),
    ('en;q=0.8,fr,ga-IE;q=0.9', 'fr'),
    # Beware of invalid headers.
    ('en;q=wtf,fr,ga-IE;q=oops', 'en-US'),
    # zh is a partial match but it's still preferred.
    ('zh, fr;q=0.8', 'zh-CN'),
    # Caps + q= sorting.
    ('ga-IE,en;q=0.8,fr;q=0.6', 'ga-IE'),
    ('fr-fr, en;q=0.8, es;q=0.2', 'fr'),
    # Consolidated languages.
    ('es-PE', 'es')
])
def test_parse_accept_language(test_input, expected):
    expected_locales = 'ga-IE', 'zh-TW', 'zh-CN', 'en-US', 'fr'
    for lang in expected_locales:
        assert lang in settings.AMO_LANGUAGES, lang
    assert urlresolvers.lang_from_accept_header(test_input) == expected


class TestShorter(TestCase):

    def test_no_shorter_language(self):
        urlresolvers.lang_from_accept_header('zh') == 'zh-CN'
        with self.settings(LANGUAGE_URL_MAP={'en-us': 'en-US'}):
            urlresolvers.lang_from_accept_header('zh') == 'en-US'
