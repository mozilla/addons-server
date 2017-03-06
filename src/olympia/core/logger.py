import logging

from olympia import core


def getLogger(name=None):
    """Wrap logging.getLogger to return a LoggerAdapter that adds extra common
    arguments to each log statement."""
    logger = logging.getLogger(name)
    return AmoLoggerAdapter(logger)


class AmoLoggerAdapter(logging.LoggerAdapter):
    """Adds the REMOTE_ADDR and USERNAME to every logging message's kwargs."""

    def __init__(self, logger, extra=None):
        super(AmoLoggerAdapter, self).__init__(logger, extra or {})

    def process(self, msg, kwargs):
        kwargs['extra'] = {
            'REMOTE_ADDR': core.get_remote_addr() or '',
            'USERNAME': getattr(core.get_user(), 'username', None) or '<anon>'
        }
        return msg, kwargs


class Formatter(logging.Formatter):
    """Formatter that makes sure REMOTE_ADDR and USERNAME are available."""

    def format(self, record):
        for name in 'REMOTE_ADDR', 'USERNAME':
            record.__dict__.setdefault(name, '')
        return super(Formatter, self).format(record)
