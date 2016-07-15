import logging
import logging.config
import logging.handlers

from django.conf import settings

import commonware.log


base_fmt = ('%(name)s:%(levelname)s %(message)s '
            ':%(pathname)s:%(lineno)s')
error_fmt = ('%(name)s:%(levelname)s %(request_path)s %(message)s '
             ':%(pathname)s:%(lineno)s')

formatters = {
    'debug': {
        '()': commonware.log.Formatter,
        'datefmt': '%H:%M:%S',
        'format': '%(asctime)s ' + base_fmt,
    },
    'prod': {
        '()': commonware.log.Formatter,
        'datefmt': '%H:%M:%S',
        'format': ('%s %s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                   % (settings.HOSTNAME, settings.SYSLOG_TAG, base_fmt)),
    },
    'prod2': {
        '()': commonware.log.Formatter,
        'datefmt': '%H:%M:%S',
        'format': ('%s %s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                   % (settings.HOSTNAME, settings.SYSLOG_TAG2, base_fmt)),
    },
    'error': {
        '()': commonware.log.Formatter,
        'datefmt': '%H:%M:%S',
        'format': ('%s %s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                   % (settings.HOSTNAME, settings.SYSLOG_TAG, error_fmt)),
    },
}

handlers = {
    'console': {
        '()': logging.StreamHandler,
        'formatter': 'debug',
    },
    'syslog': {
        'class': 'mozilla_logger.log.UnicodeHandler',
        'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
        'formatter': 'prod',
    },
    'syslog2': {
        'class': 'mozilla_logger.log.UnicodeHandler',
        'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
        'formatter': 'prod2',
    },
    'null': {
        'class': 'logging.NullHandler',
    },
    'statsd': {
        'level': 'ERROR',
        'class': 'django_statsd.loggers.errors.StatsdHandler',
    },
}

loggers = {
    'z': {},
    'amo': {},
    'django.request': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
    },
    'z.celery': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
    },
    'amo.validator': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
    },
    'caching': {
        'level': 'ERROR',
    },
    'newrelic': {
        'level': 'WARNING',
    },
    'elasticsearch': {
        'level': 'WARNING',
    },
}

cfg = {
    'version': 1,
    'filters': {},
    'formatters': formatters,
    'handlers': handlers,
    'loggers': loggers,
    'root': {},
}


def log_configure():
    """You have to explicitly call this to configure logging."""
    for key, value in settings.LOGGING.items():
        if isinstance(cfg[key], dict):
            cfg[key].update(value)
        else:
            cfg[key] = value

    USE_SYSLOG = settings.HAS_SYSLOG and not settings.DEBUG

    if USE_SYSLOG:
        cfg['loggers']['z.timer'] = {'handlers': ['syslog2']}

    # Set the level and handlers for all loggers.
    for logger in cfg['loggers'].values() + [cfg['root']]:
        if 'handlers' not in logger:
            logger['handlers'] = ['syslog' if USE_SYSLOG else 'console']
        if 'level' not in logger:
            logger['level'] = settings.LOG_LEVEL
        if logger is not cfg['root'] and 'propagate' not in logger:
            logger['propagate'] = False

    logging.config.dictConfig(cfg)
