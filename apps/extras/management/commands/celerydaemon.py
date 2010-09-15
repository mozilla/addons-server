from optparse import make_option

from django.core.management.base import BaseCommand

import daemon
import daemon.pidlockfile
from celery.bin.celeryd import run_worker, OPTION_LIST


opts = list(BaseCommand.option_list +
            filter(lambda o: '--version' not in o._long_opts, OPTION_LIST))
opts.append(make_option('--pidfile'))


class Command(BaseCommand):
    help = 'Run celery as a daemon.'
    args = '[celery_opts ...]'
    option_list = opts

    def handle(self, *args, **opts):
        pidfile = None
        if opts['pidfile']:
            pidfile = daemon.pidlockfile.PIDLockFile(opts['pidfile'])
            del opts['pidfile']

        with daemon.DaemonContext(pidfile=pidfile):
            run_worker(**opts)
