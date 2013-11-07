import logging
import json

from django.conf import settings

from nose.tools import eq_
from metlog.config import client_from_dict_config

import amo.tests
import commonware.log
from lib.log_settings_base import error_fmt


cfg = {
    'version': 1,
    'formatters': {
        'error': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%S',
            'format': ('%s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                       % (settings.SYSLOG_TAG, error_fmt)),
        },
    },
    'handlers': {
        'test_syslog': {
            'class': 'lib.misc.admin_log.ErrorSyslogHandler',
            'formatter': 'error',
        },
    },
    'loggers': {
        'test.lib.misc.logging': {
            'handlers': ['test_syslog'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}


class TestMetlogStdLibLogging(amo.tests.TestCase):

    def setUp(self):
        METLOG_CONF = {
            'sender': {
                'class': 'metlog.senders.logging.StdLibLoggingSender',
                'logger_name': 'z.metlog',
                }
            }
        self.metlog = client_from_dict_config(METLOG_CONF)
        self.logger = logging.getLogger('z.metlog')

        """
        When logging.config.dictConfig is used to configure logging
        with a 'one-shot' config dictionary, any previously
        instantiated singleton loggers (ie: all old loggers not in
        the new config) will be explicitly disabled.
        """
        self.logger.disabled = False

        self._orig_handlers = self.logger.handlers
        self.handler = logging.handlers.BufferingHandler(65536)
        self.logger.handlers = [self.handler]

    def tearDown(self):
        self.logger.handlers = self._orig_handlers

    def test_oldstyle_sends_msg(self):
        msg = 'error'
        self.metlog.error(msg)
        logrecord = self.handler.buffer[-1]
        self.assertEqual(logrecord.msg, msg)
        self.assertEqual(logrecord.levelname, 'ERROR')

        msg = 'info'
        self.metlog.info(msg)
        logrecord = self.handler.buffer[-1]
        self.assertEqual(logrecord.msg, msg)
        self.assertEqual(logrecord.levelname, 'INFO')

        msg = 'warn'
        self.metlog.warn(msg)
        logrecord = self.handler.buffer[-1]
        self.assertEqual(logrecord.msg, msg)
        self.assertEqual(logrecord.levelname, 'WARNING')

        # debug shouldn't log
        msg = 'debug'
        self.metlog.debug(msg)
        logrecord = self.handler.buffer[-1]
        self.assertNotEqual(logrecord.msg, msg)
        self.assertNotEqual(logrecord.levelname, 'DEBUG')

    def test_other_sends_json(self):
        timer = 'footimer'
        elapsed = 4
        self.metlog.timer_send(timer, elapsed)
        logrecord = self.handler.buffer[-1]
        self.assertEqual(logrecord.levelname, 'INFO')
        msg = json.loads(logrecord.msg)
        self.assertEqual(msg['type'], 'timer')
        self.assertEqual(msg['payload'], str(elapsed))
        self.assertEqual(msg['fields']['name'], timer)


class TestRaven(amo.tests.TestCase):
    def setUp(self):
        """
        We need to set the settings.METLOG instance to use a
        DebugCaptureSender so that we can inspect the sent messages.
        """

        metlog = settings.METLOG
        METLOG_CONF = {
            'logger': 'zamboni',
            'sender': {'class': 'metlog.senders.DebugCaptureSender'},
        }
        from metlog.config import client_from_dict_config
        self.metlog = client_from_dict_config(METLOG_CONF, metlog)

    def test_send_raven(self):
        try:
            1 / 0
        except:
            self.metlog.raven('blah')

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])
        eq_(msg['type'], 'sentry')
