import logging
import logging.handlers

from django.conf import settings

# Loggers created under the "z" namespace, e.g. "z.caching", will inherit the
# configuration from the base z logger.
log = logging.getLogger('z')

level = settings.LOG_LEVEL

base_fmt = ('[%(REMOTE_ADDR)s] %(name)s:%(levelname)s %(message)s '
            ':%(pathname)s:%(lineno)s')
if settings.DEBUG:
    fmt = getattr(settings, 'LOG_FORMAT', '%(asctime)s ' + base_fmt)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(fmt, datefmt='%H:%M:%S')
else:
    fmt = '%s: %s' % (settings.SYSLOG_TAG, base_fmt)
    fmt = getattr(settings, 'SYSLOG_FORMAT', fmt)
    SysLogger = logging.handlers.SysLogHandler
    handler = SysLogger(facility=SysLogger.LOG_LOCAL7)
    formatter = logging.Formatter(fmt)

log.setLevel(level)
handler.setLevel(level)
handler.setFormatter(formatter)

for f in getattr(settings, 'LOG_FILTERS', []):
    handler.addFilter(logging.Filter(f))

log.addHandler(handler)
