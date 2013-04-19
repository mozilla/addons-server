import mock
import requests
from nose.tools import eq_

import amo.tests

from lib.geoip import GeoIP


def generate_settings(url='', default='worldwide', timeout=0.2):
    return mock.Mock(GEOIP_URL=url, GEOIP_DEFAULT_VAL=default,
                     GEOIP_DEFAULT_TIMEOUT=timeout)


class GeoIPTest(amo.tests.TestCase):

    def setUp(self):
        self.create_switch(name='geoip-geodude', active=True)

    @mock.patch('requests.post')
    def test_lookup(self, mock_post):
        url = 'localhost'
        geoip = GeoIP(generate_settings(url=url))
        mock_post.return_value = mock.Mock(status_code=200, json=lambda: {
            'country_code': 'US',
            'country_name': 'United States'
        })
        ip = '1.1.1.1'
        result = geoip.lookup(ip)
        mock_post.assert_called_with('{0}/country.json'.format(url),
                                     timeout=0.2, data={'ip': ip})
        eq_(result, 'us')

    @mock.patch('requests.post')
    def test_no_url(self, mock_post):
        geoip = GeoIP(generate_settings())
        result = geoip.lookup('2.2.2.2')
        assert not mock_post.called
        eq_(result, 'worldwide')

    @mock.patch('requests.post')
    def test_bad_request(self, mock_post):
        url = 'localhost'
        geoip = GeoIP(generate_settings(url=url))
        mock_post.return_value = mock.Mock(status_code=404, json=lambda: None)
        ip = '3.3.3.3'
        result = geoip.lookup(ip)
        mock_post.assert_called_with('{0}/country.json'.format(url),
                                     timeout=0.2, data={'ip': ip})
        eq_(result, 'worldwide')

    @mock.patch('requests.post')
    def test_timeout(self, mock_post):
        url = 'localhost'
        geoip = GeoIP(generate_settings(url=url))
        mock_post.side_effect = requests.Timeout
        ip = '3.3.3.3'
        result = geoip.lookup(ip)
        mock_post.assert_called_with('{0}/country.json'.format(url),
                                     timeout=0.2, data={'ip': ip})
        eq_(result, 'worldwide')

    @mock.patch('requests.post')
    def test_connection_error(self, mock_post):
        url = 'localhost'
        geoip = GeoIP(generate_settings(url=url))
        mock_post.side_effect = requests.ConnectionError
        ip = '3.3.3.3'
        result = geoip.lookup(ip)
        mock_post.assert_called_with('{0}/country.json'.format(url),
                                     timeout=0.2, data={'ip': ip})
        eq_(result, 'worldwide')
