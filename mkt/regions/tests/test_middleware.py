import socket

from django.conf import settings

import mock
from nose.tools import eq_, ok_

import amo.tests
from users.models import UserProfile

import mkt
from mkt.site.fixtures import fixture


_langs = ['cs', 'de', 'en-US', 'es', 'fr', 'pl', 'pt-BR', 'pt-PT']


@mock.patch.object(settings, 'LANGUAGE_URL_MAP',
                   dict([x.lower(), x] for x in _langs))
class TestRegionMiddleware(amo.tests.TestCase):

    def test_lang_set_with_region(self):
        for region in ('restofworld', 'us', 'br'):
            r = self.client.get('/robots.txt?region=%s' % region)
            if region == 'restofworld':
                # Set cookie for first time only.
                eq_(r.cookies['lang'].value, settings.LANGUAGE_CODE + ',')
            else:
                eq_(r.cookies.get('lang'), None)
            eq_(r.context['request'].LANG, settings.LANGUAGE_CODE)

    def test_no_api_cookie(self):
        res = self.client.get('/api/v1/apps/schema/?region=restofworld')
        ok_(not res.cookies)

    @mock.patch('mkt.regions.set_region')
    def test_accept_good_region(self, set_region):
        for region, region_cls in mkt.regions.REGIONS_CHOICES:
            self.client.get('/api/v1/apps/?region=%s' % region)
            set_region.assert_called_with(region_cls)

    @mock.patch('mkt.regions.set_region')
    def test_ignore_bad_region(self, set_region):
        # When no region is specified or the region is invalid, we use
        # whichever region satisfies `Accept-Language`.
        for region in ('', 'BR', '<script>alert("ballin")</script>'):
            self.client.get('/api/v1/apps/?region=%s' % region,
                            HTTP_ACCEPT_LANGUAGE='fr')
            set_region.assert_called_with(mkt.regions.RESTOFWORLD)

    @mock.patch('mkt.regions.set_region')
    def test_handles_worldwide_as_restofworld(self, set_region):
        self.client.get('/api/v1/apps/?region=worldwide')
        set_region.assert_called_with(mkt.regions.RESTOFWORLD)

    @mock.patch('mkt.regions.set_region')
    @mock.patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_url_param_override(self, mock_rfr, set_region):
        self.client.get('/api/v1/apps/?region=br')
        set_region.assert_called_with(mkt.regions.BR)
        assert not mock_rfr.called

    @mock.patch('mkt.regions.set_region')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'restofworld')
    def test_geoip_missing_restofworld(self, set_region):
        """ Test for restofworld region """
        # The remote address by default is 127.0.0.1
        # Use 'sa-US' as the language to defeat the lanugage sniffer
        # Note: This may be problematic should we ever offer
        # apps in US specific derivation of SanskritRight.
        self.client.get('/api/v1/apps/', HTTP_ACCEPT_LANGUAGE='sa-US')
        set_region.assert_called_with(mkt.regions.RESTOFWORLD)

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch('mkt.regions.set_region')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'restofworld')
    def test_geoip_lookup_available(self, set_region, mock_lookup):
        mock_lookup.return_value = 'br'
        self.client.get('/api/v1/apps/', HTTP_ACCEPT_LANGUAGE='sa-US')
        set_region.assert_called_with(mkt.regions.BR)

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch('mkt.regions.set_region')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'restofworld')
    def test_geoip_lookup_unavailable(self, set_region, mock_lookup):
        lang = 'zz'
        mock_lookup.return_value = lang
        self.client.get('/api/v1/apps/', HTTP_ACCEPT_LANGUAGE='sa-US')
        set_region.assert_called_with(mkt.regions.RESTOFWORLD)

    @mock.patch('mkt.regions.set_region')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    def test_geoip_missing_lang(self, set_region):
        """ Test for US region """
        self.client.get('/api/v1/apps/', REMOTE_ADDR='127.0.0.1')
        set_region.assert_called_with(mkt.regions.US)

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    @mock.patch('mkt.regions.set_region')
    def test_geoip_down(self, set_region, mock_socket):
        """ Test that we fail gracefully if the GeoIP server is down. """
        mock_socket.connect.side_effect = IOError
        self.client.get('/api/v1/apps/', REMOTE_ADDR='127.0.0.1')
        set_region.assert_called_with(mkt.regions.US)

    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'us')
    @mock.patch('socket.socket')
    @mock.patch('mkt.regions.set_region')
    def test_geoip_timeout(self, set_region, mock_socket):
        """ Test that we fail gracefully if the GeoIP server times out. """
        mock_socket.return_value.connect.return_value = True
        mock_socket.return_value.send.side_effect = socket.timeout
        self.client.get('/api/v1/apps/', REMOTE_ADDR='127.0.0.1')
        set_region.assert_called_with(mkt.regions.US)

    @mock.patch('mkt.regions.middleware.GeoIP.lookup')
    @mock.patch('mkt.regions.set_region')
    @mock.patch.object(settings, 'GEOIP_DEFAULT_VAL', 'restofworld')
    def test_geoip_gb(self, set_region, mock_lookup):
        mock_lookup.return_value = 'gb'
        self.client.get('/api/v1/apps/', HTTP_ACCEPT_LANGUAGE='sa-US')
        set_region.assert_called_with(mkt.regions.UK)


class TestRegionMiddlewarePersistence(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def test_save_region(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.get('/api/v1/apps/?region=br')
        eq_(UserProfile.objects.get(pk=999).region, 'br')
