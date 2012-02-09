import logging
import logging.handlers

from django.conf import settings

import commonware.log
import dictconfig

base_fmt = ('%(name)s:%(levelname)s %(message)s '
            ':%(pathname)s:%(lineno)s')
error_fmt = ('%(name)s:%(levelname)s %(request_path)s %(message)s '
            ':%(pathname)s:%(lineno)s')


cfg = {
    'version': 1,
    'filters': {},
    'formatters': {
        'debug': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%S',
            'format': '%(asctime)s ' + base_fmt,
        },
        'prod': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%S',
            'format': ('%s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                       % (settings.SYSLOG_TAG, base_fmt)),
        },
        'prod2': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%S',
            'format': ('%s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                       % (settings.SYSLOG_TAG2, base_fmt)),
        },
        'error': {
            '()': commonware.log.Formatter,
            'datefmt': '%H:%M:%S',
            'format': ('%s: [%%(USERNAME)s][%%(REMOTE_ADDR)s] %s'
                       % (settings.SYSLOG_TAG, error_fmt)),
        },
    },
    'handlers': {
        'console': {
            '()': logging.StreamHandler,
            'formatter': 'debug',
        },
        'syslog': {
            'class': 'lib.misc.admin_log.UnicodeHandler',
            'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
            'formatter': 'prod',
        },
        'syslog2': {
            'class': 'lib.misc.admin_log.UnicodeHandler',
            'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
            'formatter': 'prod2',
        },
        'null': {
            'class': 'lib.misc.admin_log.NullHandler',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'lib.misc.admin_log.AdminEmailHandler'
        },
#        'statsd': {
#            'level': 'ERROR',
#            'class': 'lib.misc.admin_log.StatsdHandler',
#        },
#        'arecibo': {
#            'level': 'ERROR',
#            'class': 'lib.misc.admin_log.AreciboHandler',
#        },
        'errortype_syslog': {
            'class': 'lib.misc.admin_log.ErrorSyslogHandler',
            'facility': logging.handlers.SysLogHandler.LOG_LOCAL7,
            'formatter': 'error',
        },
    },
    'loggers': {
        'z': {},
        'django.request': {
            # Note these handlers will choose what they want to emit and when.
            'handlers': ['mail_admins', 'errortype_syslog'],#,
#                         'statsd', 'arecibo'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
    'root': {},
}

for key, value in settings.LOGGING.items():
    cfg[key].update(value)


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

dictconfig.dictConfig(cfg)
