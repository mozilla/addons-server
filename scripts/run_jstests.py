"""
A wrapper around nosetests to run JavaScript tests in a CI environment.

Example::

    python run_jstests.py --with-xunit \
                           --with-zamboni --zamboni-host hudson.mozilla.org \
                           --with-jstests \
                           --jstests-server http://jstestnet.farmdev.com/ \
                           --jstests-suite zamboni --jstests-browsers firefox

"""
import os
import site
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), '..')
assert 'manage.py' in os.listdir(ROOT), (
    'Expected this to be the root dir containing manage.py: %s' % ROOT)

site.addsitedir(os.path.join(ROOT, 'vendor'))
site.addsitedir(os.path.join(ROOT, 'vendor/lib/python'))

from jstestnetlib import webapp
from jstestnetlib.noseplugin import JSTests
import nose
from nose.plugins import Plugin


class Zamboni(Plugin):
    """Starts/stops Django runserver for tests."""
    name = 'zamboni'

    def options(self, parser, env=os.environ):
        super(Zamboni, self).options(parser, env=env)
        parser.add_option('--zamboni-host', default='0.0.0.0',
                          help='Hostname or IP address to bind manage.py '
                               'runserver to. This must match the host/ip '
                               'configured in your --jstests-suite URL. '
                               'Default: %default')
        parser.add_option('--zamboni-port', default=9877,
                          help='Port to bind manage.py runserver to. '
                               'This must match the port '
                               'configured in your --jstests-suite URL. '
                               'Default: %default')
        parser.add_option('--zamboni-log', default=None,
                          help='Log filename for the manage.py runserver '
                               'command. Logs to a temp file by default.')
        self.parser = parser

    def configure(self, options, conf):
        super(Zamboni, self).configure(options, conf)
        self.options = options

    def begin(self):
        bind = '%s:%s' % (self.options.zamboni_host,
                          self.options.zamboni_port)
        startup_url = 'http://%s/' % bind
        self.zamboni = webapp.WebappServerCmd(
                                ['python', 'manage.py', 'runserver', bind],
                                startup_url, logfile=self.options.zamboni_log,
                                cwd=ROOT)
        self.zamboni.startup()

    def finalize(self, result):
        self.zamboni.shutdown()


def main():
    nose.main(addplugins=[Zamboni(), JSTests()])


if __name__ == '__main__':
    main()
