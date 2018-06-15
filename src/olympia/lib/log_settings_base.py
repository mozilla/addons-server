import logging
import logging.config
import logging.handlers

from django.conf import settings

import olympia.core.logger

formatters = {
    'debug': {
        '()': olympia.core.logger.Formatter,
        'datefmt': '%H:%M:%S',
        'format': ('%(asctime)s %(name)s:%(levelname)s %(message)s :'
                   '%(pathname)s:%(lineno)s'),
    },
    'json': {
        '()': olympia.core.logger.JsonFormatter,
        'logger_name': settings.MOZLOG_NAME
    },
}

handlers = {
    'console': {
        '()': logging.StreamHandler,
        'formatter': 'debug',
    },
    'mozlog': {
        'level': 'DEBUG',
        'class': 'logging.StreamHandler',
        'formatter': 'json'
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
    'amo': {},
    'amo.validator': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
    },
    'django': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
    },
    'elasticsearch': {
        'level': 'WARNING',
    },
    'newrelic': {
        'level': 'WARNING',
    },
    'post_request_task': {
        # Ignore INFO or DEBUG from post-request-task, it logs too much.
        'level': 'WARNING',
    },
    'z': {},
    'z.celery': {
        'handlers': ['statsd'],
        'level': 'ERROR',
        'propagate': True,
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
    """Configure logging by augmenting settings.LOGGING with our custom
    dynamic configuration.

    This needs to be called explicitely before doing any logging."""
    for key, value in settings.LOGGING.items():
        if isinstance(cfg[key], dict):
            cfg[key].update(value)
        else:
            cfg[key] = value

    if settings.USE_MOZLOG:
        # MozLog Application Request Summary. This is the logger
        # DockerflowMiddleware uses on every request. We don't currently use
        # that middleware because it's too much logging, but it does not hurt
        # to have the logger configured correctly when USE_MOZLOG is True.
        cfg['loggers']['request.summary'] = {
            'handlers': ['mozlog'],
            'level': 'DEBUG',
        }
    # Enable mozlog handlers by default if the corresponding settings
    # are set, otherwise default to the raw basic console.
    default_handlers = []
    if settings.USE_MOZLOG:
        default_handlers.append('mozlog')
    if not default_handlers:
        default_handlers = ['console']

    # Set the level and handlers for all loggers.
    for logger in cfg['loggers'].values() + [cfg['root']]:
        if 'handlers' not in logger:
            logger['handlers'] = default_handlers
        if 'level' not in logger:
            logger['level'] = settings.LOG_LEVEL
        if logger is not cfg['root'] and 'propagate' not in logger:
            logger['propagate'] = False

    logging.config.dictConfig(cfg)
