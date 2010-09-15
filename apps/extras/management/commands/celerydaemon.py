import grp
import pwd
from optparse import make_option

from django.core.management.base import BaseCommand

import daemon
import daemon.pidlockfile
from celery.bin.celeryd import run_worker, OPTION_LIST


opts = list(BaseCommand.option_list +
            filter(lambda o: '--version' not in o._long_opts, OPTION_LIST))
opts.extend([
    make_option('--pidfile'),
    make_option('--user', help='Run celery as this user'),
    make_option('--group', help='Run celery as this group'),
])


class Command(BaseCommand):
    help = 'Run celery as a daemon.'
    args = '[celery_opts ...]'
    option_list = opts

    def handle(self, *args, **opts):
        pidfile = uid = gid = None

        if opts['pidfile']:
            pidfile = daemon.pidlockfile.PIDLockFile(opts['pidfile'])
        if opts['user']:
            uid = pwd.getpwnam(opts['user']).pw_uid
        if opts['group']:
            gid = grp.getgrnam(opts['group']).gr_gid

        del opts['pidfile'], opts['group'], opts['user']

        with daemon.DaemonContext(pidfile=pidfile, uid=uid, gid=gid):
            run_worker(**opts)
