import json
import socket

from django.conf import settings

import mock
from nose.exc import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo.tests
from amo.decorators import no_login_required
from amo.middleware import LoginRequiredMiddleware
from amo.urlresolvers import reverse

import mkt


class MiddlewareCase(amo.tests.TestCase):
    """Temporary until new lang+region detection gets QA'd."""

    def setUp(self):
        if not settings.REGION_STORES:
            raise SkipTest


_langs = ['de', 'en-US', 'es', 'fr', 'pt-BR', 'pt-PT']


@mock.patch.object(settings, 'LANGUAGES', [x.lower() for x in _langs])
class TestRedirectPrefixedURIMiddleware(MiddlewareCase):

    def test_redirect_for_good_application(self):
        for app in amo.APPS:
            r = self.client.get('/%s/' % app)
            self.assert3xx(r, '/', 302)

    def test_redirect_for_bad_application(self):
        r = self.client.get('/mosaic/')
        eq_(r.status_code, 404)

    def test_redirect_for_good_locale(self):
        redirects = [
            ('/en-US/', '/?lang=en-us'),
            ('/pt-BR/', '/?lang=pt-br'),
            ('/pt-br/', '/?lang=pt-br'),
            ('/fr/', '/?lang=fr'),
            ('/es-PE/', '/?lang=es'),
        ]
        for before, after in redirects:
            r = self.client.get(before)
            self.assert3xx(r, after, 302)

    def test_preserve_qs_for_lang(self):
        r = self.client.get('/pt-BR/firefox/privacy-policy?omg=yes')
        self.assert3xx(r, '/privacy-policy?lang=pt-br&omg=yes', 302)

        r = self.client.get('/pt-BR/privacy-policy?omg=yes')
        self.assert3xx(r, '/privacy-policy?lang=pt-br&omg=yes', 302)

    def test_switch_locale(self):
        # Locale in URL prefix takes precedence.
        r = self.client.get('/pt-BR/?lang=de')
        self.assert3xx(r, '/?lang=pt-br', 302)

    def test_no_locale(self):
        r = self.client.get('/')
        eq_(r.status_code, 200)
        r = self.client.get('/?lang=fr')
        eq_(r.status_code, 200)

    def test_redirect_for_good_region(self):
        redirects = [
            ('/worldwide/', '/?region=worldwide'),
            ('/br/', '/?region=br'),
            ('/us/', '/?region=us'),
            ('/BR/', '/?region=br'),
        ]
        for before, after in redirects:
            r = self.client.get(before)
            self.assert3xx(r, after, 302)

    def test_redirect_for_good_locale_and_region(self):
        r = self.client.get('/en-US/br/privacy-policy?omg=yes',
                            follow=True)
        # Can you believe this actually works?
        self.assert3xx(r,
            '/privacy-policy?lang=en-us&region=br&omg=yes', 302)

    def test_preserve_qs_for_region(self):
        r = self.client.get('/br/privacy-policy?omg=yes')
        self.assert3xx(r, '/privacy-policy?region=br&omg=yes', 302)

    def test_switch_region(self):
        r = self.client.get('/worldwide/?region=brazil')
        self.assert3xx(r, '/?region=worldwide', 302)

    def test_404_for_bad_prefix(self):
        for url in ['/xxx', '/xxx/search/',
                    '/brazil/', '/BRAZIL/',
                    '/pt/?lang=de', '/pt-XX/brazil/']:
            r = self.client.get(url)
            got = r.status_code
            eq_(got, 404, "For %r: expected '404' but got %r" % (url, got))


@mock.patch.object(settings, 'LANGUAGES', [x.lower() for x in _langs])
@mock.patch.object(settings, 'LANGUAGE_URL_MAP',
                   dict([x.lower(), x] for x in _langs))
class TestLocaleMiddleware(MiddlewareCase):

    def test_accept_good_locale(self):
        locales = [
            ('en-US', 'en-US', 'en-US,en-US'),
            ('pt-BR', 'pt-BR', 'pt-BR,en-US'),
            ('pt-br', 'pt-BR', None),
            ('fr', 'fr', 'fr,en-US'),
            ('es-PE', 'es', 'es,en-US'),
            ('fr', 'fr', 'fr,en-US'),
        ]
        for locale, r_lang, c_lang in locales:
            r = self.client.get('/?lang=%s' % locale)
            if c_lang:
                eq_(r.cookies['lang'].value, c_lang)
            else:
                eq_(r.cookies.get('lang'), None)
            eq_(r.context['request'].LANG, r_lang)

    def test_accept_language_and_cookies(self):
        # Your cookie tells me pt-BR but your browser tells me en-US.
        self.client.cookies['lang'] = 'pt-BR,pt-BR'
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, 'en-US,')
        eq_(r.context['request'].LANG, 'en-US')

        # Your cookie tells me pt-br but your browser tells me en-US.
        self.client.cookies['lang'] = 'pt-br,fr'
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, 'en-US,')
        eq_(r.context['request'].LANG, 'en-US')

        # Your cookie tells me pt-BR and your browser tells me pt-BR.
        self.client.cookies['lang'] = 'pt-BR,pt-BR'
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(r.cookies.get('lang'), None)
        eq_(r.context['request'].LANG, 'pt-BR')

        # You explicitly changed to fr, and your browser still tells me pt-BR.
        # So no new cookie!
        self.client.cookies['lang'] = 'fr,pt-BR'
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(r.cookies.get('lang'), None)
        eq_(r.context['request'].LANG, 'fr')

        # You explicitly changed to fr, but your browser still tells me es.
        # So make a new cookie!
        self.client.cookies['lang'] = 'fr,pt-BR'
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='es')
        eq_(r.cookies['lang'].value, 'es,')
        eq_(r.context['request'].LANG, 'es')

    def test_ignore_bad_locale(self):
        # Good? Store language.
        r = self.client.get('/?lang=fr')
        eq_(r.cookies['lang'].value, 'fr,en-US')

        # Bad? Reset language.
        r = self.client.get('/?lang=')
        eq_(r.cookies['lang'].value, 'en-US,en-US')

        # Still bad? Don't change language.
        for locale in ('xxx', '<script>alert("ballin")</script>'):
            r = self.client.get('/?lang=%s' % locale)
            eq_(r.cookies.get('lang'), None)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

        # Good? Change language.
        r = self.client.get('/?lang=fr')
        eq_(r.cookies['lang'].value, 'fr,en-US')

    def test_already_have_cookie_for_bad_locale(self):
        for locale in ('', 'xxx', '<script>alert("ballin")</script>'):
            self.client.cookies['lang'] = locale

            r = self.client.get('/')
            eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_no_cookie(self):
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')
        eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_cookie_gets_set_once(self):
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='de')
        eq_(r.cookies['lang'].value, 'de,')

        # Since we already made a request above, we should remember the lang.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='de')
        eq_(r.cookies.get('lang'), None)

    def test_accept_language(self):
        locales = [
            ('', settings.LANGUAGE_CODE),
            ('de', 'de'),
            ('en-us, de', 'en-US'),
            ('en-US', 'en-US'),
            ('fr, en', 'fr'),
            ('pt-XX, xx, yy', 'pt-PT'),
            ('pt', 'pt-PT'),
            ('pt, de', 'pt-PT'),
            ('pt-XX, xx, de', 'pt-PT'),
            ('pt-br', 'pt-BR'),
            ('pt-BR', 'pt-BR'),
            ('xx, yy, zz', settings.LANGUAGE_CODE),
            ('<script>alert("ballin")</script>', settings.LANGUAGE_CODE),
            ('en-us;q=0.5, de', 'de'),
            ('es-PE', 'es'),
        ]
        for given, expected in locales:
            r = self.client.get('/', HTTP_ACCEPT_LANGUAGE=given)

            got = r.cookies['lang'].value
            eq_(got, expected + ',',
                'For %r: expected %r but got %r' % (given, expected, got))

            got = r.context['request'].LANG
            eq_(got, expected,
                'For %r: expected %r but got %r' % (given, expected, got))

            self.client.cookies.clear()

    def test_accept_language_takes_precedence_over_previous_request(self):
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')

        # Even though you remembered my previous language, I've since
        # changed it in my browser, so let's respect that.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='fr')
        eq_(r.cookies['lang'].value, 'fr,')

    def test_accept_language_takes_precedence_over_cookie(self):
        self.client.cookies['lang'] = 'pt-BR'

        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='fr')
        eq_(r.cookies['lang'].value, 'fr,')


@mock.patch.object(settings, 'LANGUAGE_URL_MAP',
                   dict([x.lower(), x] for x in _langs))
class TestRegionMiddleware(MiddlewareCase):

    def test_lang_set_with_region(self):
        for region in ('worldwide', 'us', 'br'):
            r = self.client.get('/?region=%s' % region)
            if region == 'worldwide':
                # Set cookie for first time only.
                eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')
            else:
                eq_(r.cookies.get('lang'), None)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_accept_good_region(self):
        for region, region_cls in mkt.regions.REGIONS_CHOICES:
            r = self.client.get('/?region=%s' % region)
            eq_(r.cookies['region'].value, region)
            eq_(r.context['request'].REGION, region_cls)

    def test_already_have_cookie_for_good_region(self):
        for region in ('worldwide', 'us', 'br'):
            self.client.cookies['lang'] = 'en-US,en-US'
            self.client.cookies['region'] = region

            r = self.client.get('/')
            eq_(r.cookies.get('region'), None)
            eq_(r.context['request'].REGION,
                mkt.regions.REGIONS_DICT[region])

    def test_ignore_bad_region(self):
        # When no region is specified or the region is invalid, we use
        # whichever region satisfies `Accept-Language`.
        for region in ('', 'BR', '<script>alert("ballin")</script>'):
            self.client.cookies.clear()
            self.client.cookies['lang'] = 'fr,fr'

            r = self.client.get('/?region=%s' % region,
                                HTTP_ACCEPT_LANGUAGE='fr')
            eq_(r.cookies['region'].value, 'worldwide')
            eq_(r.context['request'].REGION, mkt.regions.WORLDWIDE)

    def test_accept_language(self):
        locales = [
            ('', 'worldwide'),
            ('de', 'worldwide'),
            ('en-us, de', 'us'),
            ('en-US', 'us'),
            ('fr, en', 'worldwide'),
            ('pt-XX, xx, yy', 'worldwide'),
            ('pt', 'worldwide'),
            ('pt, de', 'worldwide'),
            ('pt-XX, xx, de', 'worldwide'),
            ('pt-br', 'br'),
            ('pt-BR', 'br'),
            ('xx, yy, zz', 'worldwide'),
            ('<script>alert("ballin")</script>', 'worldwide'),
            ('en-us;q=0.5, de', 'worldwide'),
            ('es-PE', 'worldwide'),
        ]
        for locale, expected in locales:
            self.client.cookies.clear()

            r = self.client.get('/', HTTP_ACCEPT_LANGUAGE=locale)

            got = r.cookies['region'].value
            eq_(got, expected,
                'For %r: expected %r but got %r' % (locale, expected, got))

            got = r.context['request'].REGION.slug
            eq_(got, expected,
                'For %r: expected %r but got %r' % (locale, expected, got))

    def test_accept_language_takes_precedence_over_previous_request(self):
        r = self.client.get('/')
        eq_(r.cookies['region'].value, 'us')

        # Even though you remembered my previous language, I've since
        # changed it in my browser, so let's respect that.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='pt-br')
        eq_(r.cookies['region'].value, 'br')

    def test_accept_language_takes_precedence_over_cookie(self):
        self.client.cookies['lang'] = 'ar,ja'
        self.client.cookies['region'] = 'worldwide'

        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(r.cookies['region'].value, 'br')

    def test_not_stuck(self):
        self.client.cookies['lang'] = 'en-US,'
        self.client.cookies['region'] = 'br'
        r = self.client.get('/')
        assert not r.cookies

    # To actually test these calls with a valid GeoIP server,
    # please remove the GEOIP_NOOP overrides.
    @mock.patch.object(settings, 'GEOIP_NOOP', True)
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'worldwide')
    def test_geoip_missing_worldwide(self):
        """ Test for worldwide region """
        # The remote address by default is 127.0.0.1
        # Use 'sa-US' as the language to defeat the lanugage sniffer
        # Note: This may be problematic should we ever offer
        # apps in US specific derivation of SanskritRight.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='sa-US')
        eq_(r.cookies['region'].value, 'worldwide')

    @mock.patch.object(settings, 'GEOIP_NOOP', True)
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    def test_geoip_missing_lang(self):
        """ Test for US region """
        r = self.client.get('/', REMOTE_ADDR='mozilla.com')
        eq_(r.cookies['region'].value, 'us')

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    def test_geoip_down(self, mock_socket):
        """ Test that we fail gracefully if the GeoIP server is down. """
        mock_socket.connect.side_effect = IOError
        r = self.client.get('/', REMOTE_ADDR='mozilla.com')
        eq_(r.cookies['region'].value, 'us')

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    def test_geoip_timeout(self, mock_socket):
        """ Test that we fail gracefully if the GeoIP server times out. """
        mock_socket.return_value.connect.return_value = True
        mock_socket.return_value.send.side_effect = socket.timeout
        r = self.client.get('/', REMOTE_ADDR='mozilla.com')
        eq_(r.cookies['region'].value, 'us')


class TestVaryMiddleware(MiddlewareCase):

    def test_no_vary_cookie(self):
        # What is expected to `Vary`.
        r = self.client.get('/privacy-policy')
        eq_(r['Vary'],
            'X-Requested-With, Accept-Language, Cookie, X-Mobile, User-Agent')

        r = self.client.get('/privacy-policy', follow=True)
        eq_(r['Vary'],
            'X-Requested-With, Accept-Language, Cookie, X-Mobile, User-Agent')

    # Patching MIDDLEWARE_CLASSES because other middleware tweaks vary headers.
    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES', [
        'amo.middleware.CommonMiddleware',
        'amo.middleware.NoVarySessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'mkt.site.middleware.RequestCookiesMiddleware',
        'mkt.site.middleware.LocaleMiddleware',
        'mkt.site.middleware.RegionMiddleware',
        'mkt.site.middleware.MobileDetectionMiddleware',
        'mkt.site.middleware.GaiaDetectionMiddleware',
    ])
    def test_no_user_agent(self):
        # We've toggled the middleware to not rewrite the application and also
        # not vary headers based on User-Agent.
        self.client.login(username='31337', password='password')

        r = self.client.get('/', follow=True)
        eq_(r.status_code, 200)

        assert 'firefox' not in r.request['PATH_INFO'], (
            'Application should not be in the request URL.')
        assert 'User-Agent' not in r['Vary'], (
            'User-Agent should not be in the "Vary" header.')


class TestMobileMiddleware(amo.tests.TestCase):

    def test_no_effect(self):
        r = self.client.get('/', follow=True)
        assert not r.cookies.get('mobile')
        assert not r.context['request'].MOBILE

    def test_force_mobile(self):
        r = self.client.get('/?mobile=true', follow=True)
        eq_(r.cookies['mobile'].value, 'true')
        assert r.context['request'].MOBILE

    def test_force_unset_mobile(self):
        r = self.client.get('/?mobile=true', follow=True)
        assert r.cookies.get('mobile')

        r = self.client.get('/?mobile=false', follow=True)
        eq_(r.cookies['mobile'].value, '')
        assert not r.context['request'].MOBILE

        r = self.client.get('/', follow=True)
        eq_(r.cookies.get('mobile'), None)
        assert not r.context['request'].MOBILE


class TestGaiaMiddleware(amo.tests.TestCase):

    def test_force_gaia(self):
        r = self.client.get('/?gaia=true', follow=True)
        eq_(r.cookies['gaia'].value, 'true')
        assert r.context['request'].GAIA

    def test_force_unset_gaia(self):
        r = self.client.get('/?gaia=true', follow=True)
        assert r.cookies.get('gaia')

        r = self.client.get('/?gaia=false', follow=True)
        eq_(r.cookies['gaia'].value, '')
        assert not r.context['request'].GAIA

        r = self.client.get('/', follow=True)
        eq_(r.cookies.get('gaia'), None)
        assert not r.context['request'].GAIA


class TestHijackRedirectMiddleware(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('account.settings')

    def test_post_synchronous(self):
        r = self.client.post(self.url, {'display_name': 'omg'})
        self.assert3xx(r, self.url)

    def test_post_ajax(self):
        r = self.client.post_ajax(self.url, {'display_name': 'omg'})
        eq_(r.status_code, 200)
        eq_(json.loads(pq(r.content)('data-context'))('uri'), self.url)

    def test_post_ajax_carrier(self):
        url = '/telefonica' + self.url
        r = self.client.post_ajax(url, {'display_name': 'omg'})
        eq_(r.status_code, 200)
        eq_(json.loads(pq(r.content)('data-context'))('uri'), self.url)


def normal_view(request):
    return ''


@no_login_required
def allowed_view(request):
    return normal_view(request)


class TestLoginRequiredMiddleware(amo.tests.TestCase):

    def process(self, authenticated, view=None, url='/', lang='en-US',
                app='firefox'):
        if not view:
            view = normal_view
        request = RequestFactory().get(url, HTTP_X_PJAX=True)
        request.user = mock.Mock()
        request.APP = amo.APPS[app]
        request.LANG = lang
        request.user.is_authenticated.return_value = authenticated
        return LoginRequiredMiddleware().process_view(request, view, [], {})

    def test_middleware(self):
        # Middleware returns None if it doesn't need to redirect the user.
        assert not self.process(True)
        eq_(self.process(False).status_code, 302)

    def test_middleware_marketplace_home_skip_redirect(self):
        # Middleware returns None if it doesn't need to redirect the user.
        assert not self.process(True)
        res = self.process(False)
        eq_(res.status_code, 302)
        assert '?to=' not in res._headers['location'][1], (
            '/ should not redirect to /?to=/')

    def test_middleware_marketplace_login_skip_redirect(self):
        assert not self.process(True, url=settings.LOGIN_URL)
        res = self.process(False, url=settings.LOGIN_URL)
        eq_(res.status_code, 302)
        assert '?to=' not in res._headers['location'][1], (
            '/users/login should not redirect to /?to=/users/login')

    def test_middleware_marketplace_home_do_redirect(self):
        assert not self.process(True, url='/developers')
        res = self.process(False, url='/developers')
        eq_(res.status_code, 302)
        assert res._headers['location'][1].endswith('?to=%2Fdevelopers'), (
            '/developers should redirect to /?to=/developers')

    # Patching MIDDLEWARE_CLASSES to enable and test walled garden.
    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES',
        settings.MIDDLEWARE_CLASSES + type(settings.MIDDLEWARE_CLASSES)([
            'amo.middleware.NoConsumerMiddleware',
            'amo.middleware.LoginRequiredMiddleware'
        ])
    )
    def test_proper_redirects_with_region_stores(self):
        self.skip_if_disabled(settings.REGION_STORES)

        r = self.client.get('/')
        self.assert3xx(r, reverse('users.login'))
