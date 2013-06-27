import socket

from django.conf import settings

import mock
from nose.tools import eq_, ok_

import amo.tests
from users.models import UserProfile

import mkt
from mkt.site.fixtures import fixture


_langs = ['de', 'en-US', 'es', 'fr', 'pl', 'pt-BR', 'pt-PT']


@mock.patch.object(settings, 'LANGUAGE_URL_MAP',
                   dict([x.lower(), x] for x in _langs))
class TestRegionMiddleware(amo.tests.TestCase):

    def test_lang_set_with_region(self):
        for region in ('worldwide', 'us', 'br'):
            r = self.client.get('/robots.txt?region=%s' % region)
            if region == 'worldwide':
                # Set cookie for first time only.
                eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')
            else:
                eq_(r.cookies.get('lang'), None)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_no_api_cookie(self):
        res = self.client.get('/api/v1/apps/schema/?region=worldwide')
        ok_(not res.cookies)

    def test_accept_good_region(self):
        for region, region_cls in mkt.regions.REGIONS_CHOICES:
            r = self.client.get('/robots.txt?region=%s' % region)
            eq_(r.context['request'].REGION, region_cls)

    def test_already_have_cookie_for_good_region(self):
        for region in ('worldwide', 'us', 'br'):
            self.client.cookies['lang'] = 'en-US,en-US'
            self.client.cookies['region'] = region

            r = self.client.get('/robots.txt')
            eq_(r.cookies.get('region'), None)
            eq_(r.context['request'].REGION,
                mkt.regions.REGIONS_DICT[region])

    def test_ignore_bad_region(self):
        # When no region is specified or the region is invalid, we use
        # whichever region satisfies `Accept-Language`.
        for region in ('', 'BR', '<script>alert("ballin")</script>'):
            self.client.cookies.clear()
            self.client.cookies['lang'] = 'fr,fr'

            r = self.client.get('/robots.txt?region=%s' % region,
                                HTTP_ACCEPT_LANGUAGE='fr')
            eq_(r.context['request'].REGION, mkt.regions.WORLDWIDE)

    @mock.patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_accept_language(self, mock_rfr):
        mock_rfr.return_value = mkt.regions.WORLDWIDE.slug
        locales = [
            ('', 'worldwide'),
            ('de', 'de'),
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
            ('en-us;q=0.5, de', 'de'),
            ('es-PE', 'es'),
        ]
        for locale, expected in locales:
            self.client.cookies.clear()

            r = self.client.get('/robots.txt', HTTP_ACCEPT_LANGUAGE=locale)

            got = r.context['request'].REGION.slug
            eq_(got, expected,
                'For %r: expected %r but got %r' % (locale, expected, got))

    @mock.patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_url_param_override(self, mock_rfr):
        self.client.cookies['lang'] = 'pt-BR'
        self.client.cookies['region'] = 'br'
        r = self.client.get('/robots.txt?region=us')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['us'])
        assert not mock_rfr.called

    def test_not_stuck(self):
        self.client.cookies['lang'] = 'en-US,'
        self.client.cookies['region'] = 'br'
        r = self.client.get('/robots.txt')
        assert not r.cookies

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'worldwide')
    def test_geoip_missing_worldwide(self):
        """ Test for worldwide region """
        # The remote address by default is 127.0.0.1
        # Use 'sa-US' as the language to defeat the lanugage sniffer
        # Note: This may be problematic should we ever offer
        # apps in US specific derivation of SanskritRight.
        r = self.client.get('/robots.txt', HTTP_ACCEPT_LANGUAGE='sa-US')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['worldwide'])

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'worldwide')
    def test_geoip_lookup_available(self, mock_lookup):
        lang = 'br'
        mock_lookup.return_value = lang
        r = self.client.get('/robots.txt', HTTP_ACCEPT_LANGUAGE='sa-US')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT[lang])

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'worldwide')
    def test_geoip_lookup_unavailable_fall_to_accept_lang(self, mock_lookup):
        mock_lookup.return_value = 'worldwide'
        r = self.client.get('/robots.txt', HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['br'])

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'worldwide')
    def test_geoip_lookup_unavailable(self, mock_lookup):
        lang = 'zz'
        mock_lookup.return_value = lang
        r = self.client.get('/robots.txt', HTTP_ACCEPT_LANGUAGE='sa-US')
        eq_(r.context['request'].REGION,
            mkt.regions.REGIONS_DICT['worldwide'])

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    def test_geoip_missing_lang(self):
        """ Test for US region """
        r = self.client.get('/robots.txt', REMOTE_ADDR='mozilla.com')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['us'])

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    def test_geoip_down(self, mock_socket):
        """ Test that we fail gracefully if the GeoIP server is down. """
        mock_socket.connect.side_effect = IOError
        r = self.client.get('/robots.txt', REMOTE_ADDR='mozilla.com')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['us'])

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    def test_geoip_timeout(self, mock_socket):
        """ Test that we fail gracefully if the GeoIP server times out. """
        mock_socket.return_value.connect.return_value = True
        mock_socket.return_value.send.side_effect = socket.timeout
        r = self.client.get('/robots.txt', REMOTE_ADDR='mozilla.com')
        eq_(r.context['request'].REGION, mkt.regions.REGIONS_DICT['us'])


class TestRegionMiddlewarePersistence(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def test_save_region(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.get('/robots.txt?region=br')
        eq_(UserProfile.objects.get(pk=999).region, 'br')
