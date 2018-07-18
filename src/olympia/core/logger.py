import logging

import dockerflow.logging

from olympia import core


def getLogger(name=None):
    """Wrap logging.getLogger to return a LoggerAdapter that adds extra common
    arguments to each log statement."""
    logger = logging.getLogger(name)
    return AmoLoggerAdapter(logger)


class AmoLoggerAdapter(logging.LoggerAdapter):
    """
    Adapter adding the REMOTE_ADDR and USERNAME to every logging message's
    kwargs extra dict, which in return will automatically be merged in every
    LogRecord nstance, making those properties available for the formatter(s)
    to use.
    """

    def __init__(self, logger, extra=None):
        super(AmoLoggerAdapter, self).__init__(logger, extra or {})

    def process(self, msg, kwargs):
        kwargs['extra'] = {
            'REMOTE_ADDR': core.get_remote_addr() or '',
            'USERNAME': getattr(core.get_user(), 'username', None) or '<anon>',
        }
        return msg, kwargs


class Formatter(logging.Formatter):
    """Formatter that makes sure REMOTE_ADDR and USERNAME are available.

    Relies on AmoLoggerAdapter to make sure those variables will be set."""

    def format(self, record):
        for name in 'REMOTE_ADDR', 'USERNAME':
            record.__dict__.setdefault(name, '')
        return super(Formatter, self).format(record)


class JsonFormatter(dockerflow.logging.JsonLogFormatter):
    """Like JsonLogFormatter, but with uid and remoteAddressChain set from
    current user and ip, following mozlog format.

    See Formatter above for the legacy, console version of this."""

    def format(self, record):
        record.__dict__['uid'] = record.__dict__.pop('USERNAME', '')
        record.__dict__['remoteAddressChain'] = record.__dict__.pop(
            'REMOTE_ADDR', ''
        )
        return super(JsonFormatter, self).format(record)
