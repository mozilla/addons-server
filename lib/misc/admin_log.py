import re

NO_EMAIL_PATTERNS = {
    'IOError': re.compile(r'IOError: request data read error'),
    'TimeoutError':
        re.compile(r'TimeoutError: Request timed out after 5.000000 seconds'),
#    'OperationError':
#        re.compile(r'''OperationalError: (2006, 'MySQL server '''
#                    '''has gone away')'''),
#    'OperationError':
#        re.compile(r'''OperationalError: (2013, 'Lost connection to '''
#                    '''MySQL server during query')'''),
#    'OperationError':
#        re.compile(r'''OperationalError: (2013, "Lost connection to '''
#                    '''MySQL server at 'reading initial communication '''
#                    '''packet', system error: 0")'''),
#    'OperationError':
#        re.compile(r'''OperationalError: (1205, 'Lock wait timeout '''
#                    '''exceeded; try restarting transaction')'''),
    'ValidationError':
        re.compile(re.escape('Enter a valid date/time in YYYY-MM-DD '
                    'HH:MM[:ss[.uuuuuu]] format.')),
}

import logging
import traceback

from django.conf import settings
from django_statsd.clients import statsd
from unicode_log import UnicodeHandler

getLogger = logging.getLogger


class NullHandler(logging.Handler):

    def emit(self, record):
        pass

# Ensure the creation of the Django logger
# with a null handler. This ensures we don't get any
# 'No handlers could be found for logger "django"' messages
logger = getLogger('django')
if not logger.handlers:
    logger.addHandler(NullHandler())


class ErrorTypeHandler(logging.Handler):
    """A base class for a logging handler that examines the error."""

    def should_email(self, record):
        # Examines the record and adds an attribute to see if the
        # error should be mailed or not. Only does this once. It's up to
        # other handlers to decide to use this information.

        # If this has no exc_info or request, fail fast.
        if not record.exc_info:
            return False

        tb = '\n'.join(traceback.format_exception(*record.exc_info))
        for name, pattern in NO_EMAIL_PATTERNS.iteritems():
            if re.search(pattern, tb):
                return False

        return True

    def emitted(self, name):
        # This is currently in place for the tests. Patches welcome.
        pass


class StatsdHandler(ErrorTypeHandler):
    """Send error to statsd, we'll send this every time."""

    def emit(self, record):
        if not record.exc_info:
            return

        statsd.incr('error.%s' % record.exc_info[0].__name__.lower())
        self.emitted(self.__class__.__name__.lower())


class ErrorSyslogHandler(UnicodeHandler, ErrorTypeHandler):
    """
    Send error to syslog, only if we aren't mailing it. If there is no
    request, cope.
    """

    def emit(self, record):
        if not getattr(record, 'request', None):
            record.request_path = ''
        else:
            record.request_path = record.request.path

        UnicodeHandler.emit(self, record)
        self.emitted(self.__class__.__name__.lower())


class CallbackFilter(logging.Filter):
    """
    A logging filter that checks the return value of a given callable (which
    takes the record-to-be-logged as its only parameter) to decide whether to
    log a record.

    """
    def __init__(self, callback):
        self.callback = callback

    def filter(self, record):
        if self.callback(record):
            return 1
        return 0


class RequireDebugFalse(logging.Filter):
    def filter(self, record):
        return not settings.DEBUG
