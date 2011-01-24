import logging
import logging.handlers

from django.conf import settings

import commonware.log
import dictconfig


class NullHandler(logging.Handler):

    def emit(self, record):
        pass


base_fmt = ('%(name)s:%(levelname)s %(message)s '
            ':%(pathname)s:%(lineno)s')

cfg = {
    'version': 1,
    'filters': {},
    'formatters': {
        'debug': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%s',
            'format': '%(asctime)s ' + base_fmt,
        },
        'prod': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%s',
            'format': '%s: [%%(REMOTE_ADDR)s] %s' % (settings.SYSLOG_TAG,
                                                     base_fmt),
        },
        'prod2': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%s',
            'format': '%s: [%%(REMOTE_ADDR)s] %s' % (settings.SYSLOG_TAG2,
                                                     base_fmt),
        },
    },
    'handlers': {
        'console': {
            '()': logging.StreamHandler,
            'formatter': 'debug',
        },
        'syslog': {
            '()': logging.handlers.SysLogHandler,
            'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
            'formatter': 'prod',
        },
        'syslog2': {
            '()': logging.handlers.SysLogHandler,
            'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
            'formatter': 'prod2',
        },
        'null': {
            '()': NullHandler,
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler'
        },
    },
    'loggers': {
        'z': {},
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
    'root': {},
}

for key, value in settings.LOGGING.items():
    cfg[key].update(value)


USE_SYSLOG = settings.HAS_SYSLOG and not settings.DEBUG

if USE_SYSLOG:
    cfg['loggers']['z.timer']['handlers'] = ['syslog2']

# Set the level and handlers for all loggers.
for logger in cfg['loggers'].values() + [cfg['root']]:
    if 'handlers' not in logger:
        logger['handlers'] = ['syslog' if USE_SYSLOG else 'console']
    if 'level' not in logger:
        logger['level'] = settings.LOG_LEVEL
    if logger is not cfg['root'] and 'propagate' not in logger:
        logger['propagate'] = False

dictconfig.dictConfig(cfg)
