from __future__ import absolute_import

from metlog.client import SEVERITY
import logging


class MetlogTastypieHandler(logging.Handler):
    """
    This handler will *only* handle error level logging
    and it meant as a temporary shim to add Metlog's Raven capability
    to the standard python logging library.

    It is only intended for use with django-tastypie
    """
    def __init__(self, metlog_client):
        logging.Handler.__init__(self)
        self.metlog_client = metlog_client

    def emit(self, record):
        severity = {
                logging.DEBUG: SEVERITY.DEBUG,
                logging.INFO: SEVERITY.INFORMATIONAL,
                logging.WARNING: SEVERITY.WARNING,
                logging.ERROR: SEVERITY.ERROR,
                }.get(record.levelno, SEVERITY.CRITICAL)

        safe_dict = dict(record.__dict__)
        del safe_dict['exc_info']
        del safe_dict['msg']
        del safe_dict['args']

        self.metlog_client.raven(msg=record.msg,
            exc_info=record.exc_info,
            logger=record.name,
            severity=severity,
            args=record.args, kwargs=safe_dict)


def hook_logger(logger_name, client):
    """
    Used to hook metlog into the Python stdlib logging framework. Registers a
    logging module handler that delegates to a MetlogClient for actual message
    delivery.

    :param name: Name of the stdlib logging `logger` object for which the
                 handler should be registered.
    :param client: MetlogClient instance that the registered handler will use
                   for actual message delivery.
    """
    logger = logging.getLogger(logger_name)
    # first check to see if we're already registered
    for existing in logger.handlers:
        if (isinstance(existing, MetlogTastypieHandler) and
            existing.metlog_client is client):
            # already done, do nothing
            return
    logger.addHandler(MetlogTastypieHandler(client))
