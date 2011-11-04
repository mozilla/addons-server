import codecs
import socket

import logging
import logging.handlers

from django.conf import settings

import commonware.log
import dictconfig

from cef import cef


class NullHandler(logging.Handler):

    def emit(self, record):
        pass


class UTFFixedSysLogHandler(logging.handlers.SysLogHandler):
    """
    A bug-fix sub-class of SysLogHandler that fixes the UTF-8 BOM syslog
    bug that caused UTF syslog entries to not go to the correct
    facility.  This is fixed by over-riding the 'emit' definition
    with one that puts the BOM in the right place (after prio, instead
    of before it).

    Based on Python 2.7 version of logging.handlers.SysLogHandler.

    Bug Reference: http://bugs.python.org/issue7077
    """

    def emit(self, record):
        msg = self.format(record) + '\000'
        prio = '<%d>' % self.encodePriority(self.facility,
                             self.mapPriority(record.levelname))
        if isinstance(prio, unicode):
            prio = prio.encode('utf-8')
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        if codecs:
            msg = codecs.BOM_UTF8 + msg
        msg = prio + msg
        try:
            if self.unixsocket:
                try:
                    self.socket.send(msg)
                except socket.error:
                    self._connect_unixsocket(self.address)
                    self.socket.send(msg)
            elif self.socktype == socket.SOCK_DGRAM:
                self.socket.sendto(msg, self.address)
            else:
                self.socket.sendall(msg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


base_fmt = ('%(name)s:%(levelname)s %(message)s '
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
        'csp': {
            '()': cef.SysLogFormatter,
            'datefmt': '%H:%M:%S',
            'format': '%s: %s' % (settings.SYSLOG_CSP, base_fmt),
        },
    },
    'handlers': {
        'console': {
            '()': logging.StreamHandler,
            'formatter': 'debug',
        },
        'syslog': {
            '()': UTFFixedSysLogHandler,
            'facility': UTFFixedSysLogHandler.LOG_LOCAL7,
            'formatter': 'prod',
        },
        'syslog2': {
            '()': UTFFixedSysLogHandler,
            'facility': UTFFixedSysLogHandler.LOG_LOCAL7,
            'formatter': 'prod2',
        },
        'syslog_csp': {
            '()': UTFFixedSysLogHandler,
            'facility': UTFFixedSysLogHandler.LOG_LOCAL5,
            'formatter': 'csp',
        },
        'null': {
            '()': NullHandler,
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'admin_log.AdminEmailHandler'
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
    cfg['loggers']['z.timer'] = {'handlers': ['syslog2']}
    cfg['loggers']['z.csp'] = {'handlers': ['syslog_csp'], 'level':'WARNING'}

# Set the level and handlers for all loggers.
for logger in cfg['loggers'].values() + [cfg['root']]:
    if 'handlers' not in logger:
        logger['handlers'] = ['syslog' if USE_SYSLOG else 'console']
    if 'level' not in logger:
        logger['level'] = settings.LOG_LEVEL
    if logger is not cfg['root'] and 'propagate' not in logger:
        logger['propagate'] = False

dictconfig.dictConfig(cfg)
