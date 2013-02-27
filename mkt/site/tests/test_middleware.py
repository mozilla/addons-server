from django.conf import settings

import mock
from nose.tools import eq_
from test_utils import RequestFactory

import amo.tests

import mkt
from mkt.site.middleware import DeviceDetectionMiddleware

_langs = ['de', 'en-US', 'es', 'fr', 'pt-BR', 'pt-PT']


@mock.patch.object(settings, 'LANGUAGES', [x.lower() for x in _langs])
class TestRedirectPrefixedURIMiddleware(amo.tests.TestCase):

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
class TestLocaleMiddleware(amo.tests.TestCase):

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


class TestVaryMiddleware(amo.tests.TestCase):

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
        'mkt.regions.middleware.RegionMiddleware',
        'mkt.site.middleware.DeviceDetectionMiddleware',
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


class TestDeviceMiddleware(amo.tests.TestCase):

    devices = ['mobile', 'gaia']

    def test_no_effect(self):
        r = self.client.get('/', follow=True)
        for device in self.devices:
            assert not r.cookies.get(device)
            assert not getattr(r.context['request'], device.upper())

    def test_force(self):
        for device in self.devices:
            r = self.client.get('/?%s=true' % device, follow=True)
            eq_(r.cookies[device].value, 'true')
            assert getattr(r.context['request'], device.upper())

    def test_force_unset(self):
        for device in self.devices:
            r = self.client.get('/?%s=true' % device, follow=True)
            assert r.cookies.get(device)

            r = self.client.get('/?%s=false' % device, follow=True)
            eq_(r.cookies[device].value, '')
            assert not getattr(r.context['request'], device.upper())

    def test_persists(self):
        for device in self.devices:
            r = self.client.get('/?%s=true' % device, follow=True)
            assert r.cookies.get(device)

            r = self.client.get('/', follow=True)
            assert getattr(r.context['request'], device.upper())

    def test_xmobile(self):
        rf = RequestFactory().get('/')
        for state in [True, False]:
            rf.MOBILE = state
            DeviceDetectionMiddleware().process_request(rf)
            eq_(rf.MOBILE, state)
