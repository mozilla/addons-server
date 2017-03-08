from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

import olympia.core.logger
from olympia import amo
from olympia.applications.models import AppVersion


class Command(BaseCommand):
    use_argparse = False
    help = ('Add a new version of an application. Syntax: \n'
            '    ./manage.py addnewversion <application_name> <version>')
    log = olympia.core.logger.getLogger('z.appversions')

    def handle(self, *args, **options):
        try:
            do_addnewversion(args[0], args[1])
        except IndexError:
            raise CommandError(self.help)

        msg = 'Adding version %r to application %r\n' % (args[1], args[0])
        self.log.info(msg)
        self.stdout.write(msg)


def do_addnewversion(application, version):
    if application not in amo.APPS:
        raise CommandError('Application %r does not exist.' % application)
    try:
        AppVersion.objects.create(application=amo.APPS[application].id,
                                  version=version)
    except IntegrityError, e:
        raise CommandError('Version %r already exists: %r' % (version, e))
