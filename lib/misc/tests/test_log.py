import logging

from django.conf import settings

from heka.config import client_from_dict_config

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


class TestHekaStdLibLogging(amo.tests.TestCase):
    """
    The StdLibLoggingStream is only used for *debugging* purposes.

    Some detail is lost when you write out to a StdLibLoggingStream -
    specifically the logging level.
    """

    def setUp(self):
        super(TestHekaStdLibLogging, self).setUp()
        HEKA_CONF = {
            'encoder': 'heka.encoders.StdlibPayloadEncoder',
            'stream': {
                'class': 'heka.streams.logging.StdLibLoggingStream',
                'logger_name': 'z.heka'}}
        self.heka = client_from_dict_config(HEKA_CONF)
        self.logger = logging.getLogger('z.heka')

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
        super(TestHekaStdLibLogging, self).tearDown()

    def test_oldstyle_sends_msg(self):
        msg = 'an error'
        self.heka.error(msg)
        logrecord = self.handler.buffer[-1]
        assert logrecord.msg == "oldstyle: %s" % msg
        assert logrecord.levelno == logging.ERROR

        msg = 'info'
        self.heka.info(msg)
        logrecord = self.handler.buffer[-1]

        assert logrecord.msg == "oldstyle: %s" % msg
        assert logrecord.levelname == 'INFO'

        msg = 'warn'
        self.heka.warn(msg)
        logrecord = self.handler.buffer[-1]
        assert logrecord.msg == "oldstyle: %s" % msg
        assert logrecord.levelno == logging.WARN
        assert logrecord == self.handler.buffer[-1]

    def test_other_sends_json(self):
        timer = 'footimer'
        elapsed = 4
        self.heka.timer_send(timer, elapsed)
        logrecord = self.handler.buffer[-1]
        assert logrecord.levelno == logging.INFO
        assert logrecord.msg == "timer: %s" % str(elapsed)


class TestRaven(amo.tests.TestCase):
    def setUp(self):
        """
        We need to set the settings.HEKA instance to use a
        DebugCaptureStream so that we can inspect the sent messages.
        """
        super(TestRaven, self).setUp()

        heka = settings.HEKA
        HEKA_CONF = {
            'logger': 'zamboni',
            'stream': {'class': 'heka.streams.DebugCaptureStream'},
            'encoder': 'heka.encoders.NullEncoder'
        }
        from heka.config import client_from_dict_config
        self.heka = client_from_dict_config(HEKA_CONF, heka)

    def test_send_raven(self):
        try:
            1 / 0
        except:
            self.heka.raven('blah')

        assert len(self.heka.stream.msgs) == 1
        msg = self.heka.stream.msgs[0]
        assert msg.type == 'sentry'
