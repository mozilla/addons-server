import logging
import logging.handlers

from django.conf import settings

# Loggers created under the "z" namespace, e.g. "z.caching", will inherit the
# configuration from the base z logger.
log = logging.getLogger('z')

level = settings.LOG_LEVEL

base_fmt = ('%(name)s:%(levelname)s %(message)s '
            ':%(pathname)s:%(lineno)s')
if settings.DEBUG:
    fmt = getattr(settings, 'LOG_FORMAT', '%(asctime)s ' + base_fmt)
    handler, root_handler = logging.StreamHandler(), logging.StreamHandler()
    formatter = logging.Formatter(fmt, datefmt='%H:%M:%S')
    root_handler.setFormatter(formatter)
else:
    SysLogger = logging.handlers.SysLogHandler
    handler = SysLogger(facility=SysLogger.LOG_LOCAL7)

    # Use a root formatter that's known to be safe.
    root_handler = SysLogger(facility=SysLogger.LOG_LOCAL7)
    root_handler.setFormatter(
        logging.Formatter('%s: %s' % settings.SYSLOG_TAG, base_fmt))

    fmt = '%s: [%(REMOTE_ADDR)s] %s' % (settings.SYSLOG_TAG, base_fmt)
    fmt = getattr(settings, 'SYSLOG_FORMAT', fmt)
    formatter = logging.Formatter(fmt)

# Set a root handler to catch everything else.
logging.getLogger().addHandler(root_handler)

log.setLevel(level)
handler.setLevel(level)
handler.setFormatter(formatter)

for f in getattr(settings, 'LOG_FILTERS', []):
    handler.addFilter(logging.Filter(f))

log.addHandler(handler)
