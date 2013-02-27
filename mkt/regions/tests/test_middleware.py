import socket

from django.conf import settings

import mock
from nose.tools import eq_

import amo.tests

import mkt


_langs = ['de', 'en-US', 'es', 'fr', 'pt-BR', 'pt-PT']


@mock.patch.object(settings, 'LANGUAGE_URL_MAP',
                   dict([x.lower(), x] for x in _langs))
class TestRegionMiddleware(amo.tests.TestCase):

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
            ('es-PE', 'spain'),
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
