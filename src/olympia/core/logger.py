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
        kwargs.setdefault('extra', {}).update({
            'REMOTE_ADDR': core.get_remote_addr() or '',
            'USERNAME': getattr(core.get_user(), 'username', None) or '<anon>'
        })
        return msg, kwargs


class JsonFormatter(dockerflow.logging.JsonLogFormatter):
    """Like JsonLogFormatter, but with uid and remoteAddressChain set from
    current user and ip, following mozlog format, as well as an additional
    severity field at the root of the output for stackdriver."""

    # Map from Python logging levels to Stackdriver severity levels
    STACKDRIVER_LEVEL_MAP = {
        # 800 is EMERGENCY but Python doesn't have that
        # 700 is ALERT but Python doesn't have that
        logging.CRITICAL: 600,
        logging.ERROR: 500,
        logging.WARNING: 400,
        # 300 is NOTICE but Python doesn't have that
        logging.INFO: 200,
        logging.DEBUG: 100,
        logging.NOTSET: 0,
    }

    def convert_record(self, record):
        # Modify the record to include uid and remoteAddressChain
        record.__dict__['uid'] = record.__dict__.pop('USERNAME', '')
        record.__dict__['remoteAddressChain'] = record.__dict__.pop(
            'REMOTE_ADDR', '')
        if record.exc_info is not False:
            # Call the parent implementation to get most of the return value built.
            out = super().convert_record(record)

            # Add custom keys for stackdriver that need to live at the root level.
            out['severity'] = self.STACKDRIVER_LEVEL_MAP.get(record.levelno, 0)
            return out
