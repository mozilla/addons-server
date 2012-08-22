import socket
import mock
from nose.tools import eq_

import amo.tests

from lib.geoip import GeoIP


class NOOP_Settings:

    GEOIP_DEFAULT_VAL = 'worldwide'


class GeoIPTest(amo.tests.TestCase):

    def setUp(self):
        # Use GEOIP_NOOP to always return the default value.
        # This *should* be properly tested against a call to a GeoIP server.
        self.geoip = GeoIP(NOOP_Settings)

    @mock.patch('socket.socket')
    def test_lookup(self, mock_socket):
        send_value = 'mozilla.com'
        mock_socket.return_value.connect.return_value = True
        rcv = list('{"success":{"country_code":"us"}}')
        # 5 = prefixed "GET " and new line
        mock_socket.return_value.send.return_value = len(send_value) + 5
        mock_socket.return_value.recv.side_effect = rcv
        result = self.geoip.lookup(send_value)
        eq_(result, 'us')

    @mock.patch('socket.socket')
    def test_no_connect(self, mock_socket):
        mock_socket.return_value.connect.side_effect = IOError
        result = self.geoip.lookup('mozilla.com')
        eq_(result, 'worldwide')

    @mock.patch('socket.socket')
    def test_timeout(self, mock_socket):
        mock_socket.return_value.connect.return_value = True
        mock_socket.return_value.send.side_effect = socket.timeout
        result = self.geoip.lookup('mozilla.com')
        eq_(result, 'worldwide')
