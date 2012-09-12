import json
import logging
import socket
from django_statsd.clients import statsd

from mkt import regions


class GeoIP:
    """ Call to local GeoIP server to resolve an IP to Geo Info block """

    def __init__(self, settings):
        # I attempt to make this fairly fault proof. We don't want to
        # call the service directly, because bad data would cause the
        # C library to segfault and take out the server, so we isolate
        # that data to an external service. We also pack in as many
        # default values as possible to prevent unexpected results.
        self.noop = getattr(settings, 'GEOIP_NOOP', False)
        self.timeout = float(getattr(settings, 'GEOIP_DEFAULT_TIMEOUT', .2))
        self.host = getattr(settings, 'GEOIP_HOST', 'localhost')
        self.port = int(getattr(settings, 'GEOIP_PORT', '5309'))
        self.default_val = getattr(settings, 'GEOIP_DEFAULT_VAL',
                regions.US.slug).lower()
        # Changing this value is ONLY useful for testing.
        self.socket_lib = getattr(settings, 'GEOIP_TEST_SOCKETLIB',
                socket)

    def lookup(self, address):
        """ Resolve an IP address to a block of geo information.

        If a given address is unresolvable, return the default
        as defined by the settings, or "worldwide".
        """
        if self.noop:
            return self.default_val
        sock = self.socket_lib
        gsocket = sock.socket(socket.AF_INET, socket.SOCK_STREAM)
        gsocket.settimeout(self.timeout)
        gsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with statsd.timer('z.geoip'):
            try:
                gsocket.connect((self.host, self.port))
                # Remember, we're using a timeout, so don't call makefile()!
                send = 'GET %s\n' % address
                tsent = 0
                while tsent < len(send):
                    sent = gsocket.send(send[tsent:])
                    if sent == 0:
                        raise IOError('Socket connection broken')
                    tsent += sent
                rcv = ''
                while True:
                    try:
                        rcvm = gsocket.recv(1)
                        if len(rcvm) == 0:
                            break
                    except StopIteration:
                        # This is required for unit testing.
                        break
                    rcv += rcvm
                reply = json.loads(rcv)
                if 'error' in reply:
                    return self.default_val
                else:
                    return reply['success']['country_code'].lower()
            except socket.timeout:
                logging.warn('GeoIP server timeout. '
                             'Returning default')
                return self.default_val
            except IOError, e:
                logging.error('GeoIP server down or missing')
                return self.default_val
            except Exception, e:
                logging.error('Unknown exception: %s', str(e))
                return self.default_val
            finally:
                gsocket.close()
