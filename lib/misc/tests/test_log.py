import dictconfig
import logging
import sys

from django.conf import settings
from django.core import mail

from mock import Mock, patch
from nose.tools import eq_

import amo.tests
import commonware.log
from lib.misc.admin_log import ErrorTypeHandler
from lib.log_settings_base import error_fmt
from test_utils import RequestFactory

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
        'test_mail_admins': {
            'class': 'lib.misc.admin_log.AdminEmailHandler'
        },
        'test_statsd_handler': {
            'class': 'lib.misc.admin_log.StatsdHandler',
        },
        'test_arecibo_handler': {
            'class': 'lib.misc.admin_log.AreciboHandler',
        }
    },
    'loggers': {
        'test.lib.misc.logging': {
            'handlers': ['test_mail_admins',
                         'test_syslog',
                         'test_statsd_handler',
                         'test_arecibo_handler'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}


class TestErrorLog(amo.tests.TestCase):

    def setUp(self):
        dictconfig.dictConfig(cfg)
        self.log = logging.getLogger('test.lib.misc.logging')
        self.request = RequestFactory().get('http://foo.com/blargh')

    def division_error(self):
        try:
            1 / 0
        except:
            return sys.exc_info()

    def io_error(self):
        class IOError(Exception):
            pass
        try:
            raise IOError('request data read error')
        except:
            return sys.exc_info()

    def fake_record(self, exc_info):
        record = Mock()
        record.exc_info = exc_info
        record.should_email = None
        return record

    def test_should_email(self):
        et = ErrorTypeHandler()
        assert et.should_email(self.fake_record(self.division_error()))

    def test_should_not_email(self):
        et = ErrorTypeHandler()
        assert not et.should_email(self.fake_record(self.io_error()))

    @patch('lib.misc.admin_log.ErrorTypeHandler.emitted')
    @patch.object(settings, 'ARECIBO_SERVER_URL', 'something')
    def test_called_email(self, emitted):
        self.log.error('blargh!',
                       exc_info=self.division_error(),
                       extra={'request': self.request})
        eq_(set([n[0][0] for n in emitted.call_args_list]),
            set(['adminemailhandler', 'errorsysloghandler',
                 'statsdhandler', 'arecibohandler']))

    @patch('lib.misc.admin_log.ErrorTypeHandler.emitted')
    @patch.object(settings, 'ARECIBO_SERVER_URL', 'something')
    def test_called_no_email(self, emitted):
        self.log.error('blargh!',
                       exc_info=self.io_error(),
                       extra={'request': self.request})
        eq_(set([n[0][0] for n in emitted.call_args_list]),
            set(['errorsysloghandler', 'statsdhandler']))

    @patch('lib.misc.admin_log.ErrorTypeHandler.emitted')
    @patch.object(settings, 'ARECIBO_SERVER_URL', 'something')
    def test_no_exc_info_request(self, emitted):
        self.log.error('blargh!')
        eq_(set([n[0][0] for n in emitted.call_args_list]),
            set([]))
