import sys
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.core import logger


log = logger.getLogger('z.cron')


class Command(BaseCommand):
    help = 'Run one of the predefined cron jobs'
    args = '[name args...]'

    def handle(self, *args, **opts):
        if not args:
            log.error("Cron called without args")
            print 'These jobs are available:\n%s' % '\n'.join(
                sorted(settings.CRON_JOBS.keys()))
            sys.exit(1)

        name, args = args[0], args[1:]
        path = settings.CRON_JOBS.get(name)
        if not path:
            log.error("Cron called with an unknown cron job: %s %s" %
                      (name, args))
            print 'Unrecognized job name: %s' % name
            sys.exit(1)

        module = import_module(path)

        log.info("Beginning job: %s %s" % (name, args))
        getattr(module, name)(*args)
        log.info("Ending job: %s %s" % (name, args))
