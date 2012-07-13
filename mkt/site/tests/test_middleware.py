from django.conf import settings

import mock
from nose.exc import SkipTest
from nose.tools import eq_
from test_utils import RequestFactory

import amo.tests
from amo.decorators import no_login_required
from amo.middleware import LoginRequiredMiddleware

import mkt


class MiddlewareCase(amo.tests.TestCase):
    """Temporary until new lang+region detection gets QA'd."""

    def setUp(self):
        if not settings.REGION_STORES:
            raise SkipTest


class TestFixLegacyLocaleMiddleware(MiddlewareCase):

    def test_redirect_for_good_locale(self):
        locales = [
            ('en-US', 'en-us'),
            ('pt-BR', 'pt-br'),
            ('pt-br', 'pt-br'),
            ('fr', 'fr'),
            ('es-PE', 'es'),
        ]
        for given, expected in locales:
            r = self.client.get('/%s/' % given)
            self.assertRedirects(r, '/?lang=%s' % expected, 302)

    def test_404_for_bad_locale(self):
        r = self.client.get('/xxx/')
        eq_(r.status_code, 404)
        r = self.client.get('/pt/?lang=de')
        eq_(r.status_code, 404)

    def test_preserve_qs(self):
        r = self.client.get('/pt-BR/privacy-policy?omg=yes')
        self.assertRedirects(r, '/privacy-policy?lang=pt-br&omg=yes', 302)

    def test_switch_locale(self):
        r = self.client.get('/pt-BR/?lang=de')
        self.assertRedirects(r, '/?lang=pt-br', 302)

    def test_no_locale(self):
        r = self.client.get('/')
        eq_(r.status_code, 200)
        r = self.client.get('/?lang=fr')
        eq_(r.status_code, 200)


class TestLocaleMiddleware(MiddlewareCase):

    def test_accept_good_locale(self):
        locales = [
            ('en-US', 'en-US'),
            ('pt-BR', 'pt-BR'),
            ('pt-br', 'pt-BR'),
            ('fr', 'fr'),
            ('es-PE', 'es'),
        ]
        for given, expected in locales:
            r = self.client.get('/?lang=%s' % given)
            eq_(r.cookies['lang'].value, expected)
            eq_(r.context['request'].LANG, expected)

    def test_already_have_cookie_for_good_locale(self):
        for locale in ('pt-BR', 'pt-br'):
            self.client.cookies['lang'] = locale

            r = self.client.get('/')
            eq_(r.cookies['lang'].value, 'pt-BR')
            eq_(r.context['request'].LANG, 'pt-BR')

    def test_ignore_bad_locale(self):
        for locale in ('', 'xxx', '<script>alert("ballin")</script>'):
            r = self.client.get('/?lang=%s' % locale)
            eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_already_have_cookie_for_bad_locale(self):
        for locale in ('', 'xxx', '<script>alert("ballin")</script>'):
            self.client.cookies['lang'] = locale

            r = self.client.get('/')
            eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_no_cookie(self):
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE)
        eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_cookie_gets_set_once(self):
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='de')
        eq_(r.cookies['lang'].value, 'de')

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
            eq_(got, expected,
                'For %r: expected %r but got %r' % (given, expected, got))

            got = r.context['request'].LANG
            eq_(got, expected,
                'For %r: expected %r but got %r' % (given, expected, got))

            self.client.cookies.clear()

    def test_accept_language_takes_precedence_over_cookie(self):
        r = self.client.get('/')
        eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE)

        # Even though you remembered my previous language, I've since
        # changed it in my browser, so let's respect that.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='fr')
        eq_(r.cookies['lang'].value, 'fr')


class TestRegionMiddleware(MiddlewareCase):

    def test_lang_set_with_region(self):
        for region in ('worldwide', 'usa', 'brazil'):
            r = self.client.get('/?region=%s' % region)
            eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_accept_good_region(self):
        for region in ('worldwide', 'usa', 'brazil'):
            r = self.client.get('/?region=%s' % region)
            eq_(r.cookies['region'].value, region)
            eq_(r.context['request'].REGION,
                mkt.regions.REGIONS_DICT[region])

    def test_already_have_cookie_for_good_region(self):
        for region in ('worldwide', 'usa', 'brazil'):
            self.client.cookies['region'] = region

            r = self.client.get('/')
            eq_(r.cookies.get('region'), None)
            eq_(r.context['request'].REGION,
                mkt.regions.REGIONS_DICT[region])

    def test_ignore_bad_region(self):
        # When no region is specified or the region is invalid, we use
        # whichever region satisfies `Accept-Language`.
        for region in ('', 'BRAZIL', '<script>alert("ballin")</script>'):
            self.client.cookies.clear()

            r = self.client.get('/?region=%s' % region)
            eq_(r.cookies['region'].value, 'worldwide')
            eq_(r.context['request'].REGION, mkt.regions.WORLDWIDE)

    def test_already_have_cookie_for_bad_region(self):
        for region in ('', 'BRAZIL', '<script>alert("ballin")</script>'):
            self.client.cookies['region'] = region

            r = self.client.get('/')
            eq_(r.cookies['region'].value, 'worldwide')
            eq_(r.context['request'].REGION, mkt.regions.WORLDWIDE)

    def test_accept_language(self):
        locales = [
            ('', 'worldwide'),
            ('de', 'worldwide'),
            ('en-us, de', 'usa'),
            ('en-US', 'usa'),
            ('fr, en', 'worldwide'),
            ('pt-XX, xx, yy', 'worldwide'),
            ('pt', 'worldwide'),
            ('pt, de', 'worldwide'),
            ('pt-XX, xx, de', 'worldwide'),
            ('pt-br', 'brazil'),
            ('pt-BR', 'brazil'),
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

    def test_accept_language_takes_precedence_over_cookie(self):
        r = self.client.get('/')
        eq_(r.cookies['region'].value, 'worldwide')

        # Even though you remembered my previous language, I've since
        # changed it in my browser, so let's respect that.
        r = self.client.get('/', HTTP_ACCEPT_LANGUAGE='pt-br')
        eq_(r.cookies['region'].value, 'brazil')


class TestVaryMiddleware(MiddlewareCase):

    def test_no_vary_cookie(self):
        # What is expected to `Vary`.
        r = self.client.get('/privacy-policy')
        eq_(r['Vary'],
            'X-Requested-With, Accept-Language, X-Mobile, User-Agent')

        # But we do prevent `Vary: Cookie`.
        self.client.cookies.clear()
        r = self.client.get('/privacy-policy', follow=True)
        eq_(r['Vary'],
            'X-Requested-With, Accept-Language, X-Mobile, User-Agent')

    # Patching MIDDLEWARE_CLASSES because other middleware tweaks vary headers.
    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES', [
        'amo.middleware.CommonMiddleware',
        'amo.middleware.NoVarySessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'mkt.site.middleware.RequestCookiesMiddleware',
        'mkt.site.middleware.LocaleMiddleware',
        'mkt.site.middleware.RegionMiddleware',
    ])
    def test_no_user_agent(self):
        # We've toggled the middleware to not rewrite the application and also
        # not vary headers based on User-Agent.
        self.client.login(username='31337', password='password')

        r = self.client.get('/apps/', follow=True)
        eq_(r.status_code, 200)

        assert 'firefox' not in r.request['PATH_INFO'], (
            'Application should not be in the request URL.')
        assert 'User-Agent' not in r['Vary'], (
            'User-Agent should not be in the "Vary" header.')


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
