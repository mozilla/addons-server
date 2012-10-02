from django import test, shortcuts
from django.conf import settings
from django.core.urlresolvers import set_script_prefix

from nose.tools import eq_, assert_not_equal
import test_utils

import amo.tests
from amo import urlresolvers
from amo.middleware import LocaleAndAppURLMiddleware


class MiddlewareTest(test.TestCase):
    """Tests that the locale and app redirection work properly."""

    def setUp(self):
        self.rf = test_utils.RequestFactory()
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

            # /admin doesn't get an app.
            '/developers': '/en-US/developers',
        }

        for path, location in redirections.items():
            response = self.middleware.process_request(self.rf.get(path))
            eq_(response.status_code, 301)
            eq_(response['Location'], location)

    def process(self, *args, **kwargs):
        request = self.rf.get(*args, **kwargs)
        return self.middleware.process_request(request)

    def test_no_redirect(self):
        # /services doesn't get an app or locale.
        response = self.process('/services')
        assert response is None

    def test_vary(self):
        response = self.process('/')
        eq_(response['Vary'], 'Accept-Language, User-Agent')

        response = self.process('/firefox')
        eq_(response['Vary'], 'Accept-Language')

        response = self.process('/en-US')
        eq_(response['Vary'], 'User-Agent')

        response = self.process('/en-US/thunderbird')
        assert 'Vary' not in response

    def test_no_redirect_with_script(self):
        response = self.process('/services', SCRIPT_NAME='/oremj')
        assert response is None

    def test_get_app(self):
        def check(url, expected, ua):
            response = self.process(url, HTTP_USER_AGENT=ua)
            eq_(response['Location'], expected)

        check('/en-US/', '/en-US/firefox/', 'Firefox')
        check('/de/', '/de/mobile/', 'Fennec')

        # Mobile gets priority because it has both strings in its UA...
        check('/de/', '/de/mobile/', 'Firefox Fennec')

        # SeaMonkey gets priority because it has both strings in its UA...
        check('/en-US/', '/en-US/seamonkey/', 'Firefox SeaMonkey')

        # Android can found by its user agent.
        check('/en-US/', '/en-US/android/', 'Fennec/12.0.1')
        check('/en-US/', '/en-US/android/', 'Fennec/12')
        check('/en-US/', '/en-US/android/', 'Fennec/11.0')
        check('/en-US/', '/en-US/mobile/', 'Fennec/10.9.1')
        check('/en-US/', '/en-US/mobile/', 'Fennec/10.9')

        # And the user agent changed again.
        check('/en-US/', '/en-US/android/',
              'Mozilla/5.0 (Android; Mobile; rv:17.0) Gecko/17.0 Firefox/17.0')

        # And the user agent yet changed again.
        check('/en-US/', '/en-US/android/',
              'Mozilla/5.0 (Mobile; rv:18.0) Gecko/18.0 Firefox/18.0')

    def test_get_lang(self):
        def check(url, expected):
            response = self.process(url)
            eq_(response['Location'], expected)

        check('/services?lang=fr', '/services')
        check('/en-US/firefox?lang=fr', '/fr/firefox/')
        check('/de/admin/?lang=fr&foo=bar', '/fr/admin/?foo=bar')
        check('/en-US/firefox/?lang=fake', '/en-US/firefox/')
        check('/firefox/?lang=fr', '/fr/firefox/')
        check('/firefox/?lang=fake', '/en-US/firefox/')
        check('/en-US/extensions/?foo=fooval&bar=barval&lang=fr',
              '/fr/firefox/extensions/?foo=fooval&bar=barval')
        check('/en-US/firefox?lang=es-PE', '/es/firefox/')


class TestPrefixer:

    def tearDown(self):
        urlresolvers.clean_url_prefixes()
        set_script_prefix('/')

    def test_split_path(self):

        def split_eq(url, locale, app, path):
            rf = test_utils.RequestFactory()
            prefixer = urlresolvers.Prefixer(rf.get(url))
            actual = (prefixer.locale, prefixer.app, prefixer.shortened_path)
            eq_(actual, (locale, app, path))

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
        rf = test_utils.RequestFactory()
        prefixer = urlresolvers.Prefixer(rf.get('/'))

        eq_(prefixer.fix('/'), '/en-US/firefox/')
        eq_(prefixer.fix('/foo'), '/en-US/firefox/foo')
        eq_(prefixer.fix('/foo/'), '/en-US/firefox/foo/')
        eq_(prefixer.fix('/admin'), '/en-US/admin')
        eq_(prefixer.fix('/admin/'), '/en-US/admin/')

        prefixer.locale = 'de'
        prefixer.app = 'thunderbird'

        eq_(prefixer.fix('/'), '/de/thunderbird/')
        eq_(prefixer.fix('/foo'), '/de/thunderbird/foo')
        eq_(prefixer.fix('/foo/'), '/de/thunderbird/foo/')
        eq_(prefixer.fix('/admin'), '/de/admin')
        eq_(prefixer.fix('/admin/'), '/de/admin/')

    def test_reverse(self):
        # Make sure it works outside the request.
        eq_(urlresolvers.reverse('home'), '/')

        # With a request, locale and app prefixes work.
        client = test.Client()
        client.get('/')
        eq_(urlresolvers.reverse('home'), '/en-US/firefox/')

    def test_script_name(self):
        rf = test_utils.RequestFactory()
        request = rf.get('/foo', SCRIPT_NAME='/oremj')
        prefixer = urlresolvers.Prefixer(request)
        eq_(prefixer.fix(prefixer.shortened_path), '/oremj/en-US/firefox/foo')

        # Now check reverse.
        urlresolvers.set_url_prefix(prefixer)
        set_script_prefix('/oremj')
        eq_(urlresolvers.reverse('home'), '/oremj/en-US/firefox/')


class TestPrefixerActivate(amo.tests.TestCase):

    def test_activate_locale(self):
        with self.activate(locale='fr'):
            eq_(urlresolvers.reverse('home'), '/fr/firefox/')
        eq_(urlresolvers.reverse('home'), '/en-US/firefox/')

    def test_activate_app(self):
        with self.activate(app='mobile'):
            eq_(urlresolvers.reverse('home'), '/en-US/mobile/')
        eq_(urlresolvers.reverse('home'), '/en-US/firefox/')

    def test_activate_app_locale(self):
        with self.activate(locale='de', app='thunderbird'):
            eq_(urlresolvers.reverse('home'), '/de/thunderbird/')
        eq_(urlresolvers.reverse('home'), '/en-US/firefox/')


def test_redirect():
    """Make sure django.shortcuts.redirect uses our reverse."""
    test.Client().get('/')
    redirect = shortcuts.redirect('home')
    eq_(redirect['Location'], '/en-US/firefox/')


def test_outgoing_url():
    redirect_url = settings.REDIRECT_URL
    secretkey = settings.REDIRECT_SECRET_KEY
    exceptions = settings.REDIRECT_URL_WHITELIST
    settings.REDIRECT_URL = 'http://example.net'
    settings.REDIRECT_SECRET_KEY = 'sekrit'
    settings.REDIRECT_URL_WHITELIST = ['nicedomain.com']

    try:
        myurl = 'http://example.com'
        s = urlresolvers.get_outgoing_url(myurl)

        # Regular URLs must be escaped.
        eq_(s,
            'http://example.net/bc7d4bb262c9f0b0f6d3412ede7d3252c2e311bb1d55f6'
            '2315f636cb8a70913b/'
            'http%3A//example.com')

        # No double-escaping of outgoing URLs.
        s2 = urlresolvers.get_outgoing_url(s)
        eq_(s, s2)

        evil = settings.REDIRECT_URL.rstrip('/') + '.evildomain.com'
        s = urlresolvers.get_outgoing_url(evil)
        assert_not_equal(s, evil,
                         'No subdomain abuse of double-escaping protection.')

        nice = 'http://nicedomain.com/lets/go/go/go'
        eq_(nice, urlresolvers.get_outgoing_url(nice))

    finally:
        settings.REDIRECT_URL = redirect_url
        settings.REDIRECT_SECRET_KEY = secretkey
        settings.REDIRECT_URL_WHITELIST = exceptions


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


def test_parse_accept_language():
    check = lambda x, y: eq_(urlresolvers.lang_from_accept_header(x), y)
    expected = 'ga-IE', 'zh-TW', 'zh-CN', 'en-US', 'fr'
    for lang in expected:
        assert lang in settings.AMO_LANGUAGES, lang
    d = (('ga-ie', 'ga-IE'),
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
         ('es-PE', 'es'),
    )
    for x, y in d:
        yield check, x, y
