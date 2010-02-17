import sys

from django.conf import settings
from django.core.management.base import BaseCommand

import cronjobs


class Command(BaseCommand):
    help = 'Run a script, often a cronjob'
    args = '[name args...]'

    def handle(self, *args, **opts):
        # Load up all the cron scripts.
        for app in settings.INSTALLED_APPS:
            try:
                __import__('%s.cron' % app)
            except ImportError:
                pass

        registered = cronjobs.registered

        if not args:
            print 'Try one of these: %s' % ', '.join(registered)
            sys.exit(1)

        script, args = args[0], args[1:]
        if script not in registered:
            print 'Unrecognized name: %s' % script
            sys.exit(1)

        registered[script](*args)
