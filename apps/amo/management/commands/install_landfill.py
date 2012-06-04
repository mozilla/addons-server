from datetime import date
from optparse import make_option
import os
import shlex
from subprocess import Popen, PIPE

from django.conf import settings
from django.core.management.base import BaseCommand

from zadmin.models import Config


class Command(BaseCommand):
    help = """
    Install a new landfill database. Requires that the database already exists.
    Landfill destroys and remakes each table before putting data into it. This
    is important to note as you'll have to rerun any migrations and you'll lose
    any custom data you've loaded.

    Requires that you have gzcat installed (default on most *nix).
    """
    option_list = BaseCommand.option_list + (
        make_option('--no-notice',
                    action='store_true',
                    dest='no_notice',
                    default=False,
                    help='Remove landfill site notice'),
        make_option('--no-download',
                    action='store_true',
                    dest='no_download',
                    default=False,
                    help='Use already downloaded landfill file.'),
        )

    def handle(self, *args, **kw):
        filename = date.today().strftime('landfill-%Y-%m-%d.sql.gz')
        file_location = '/tmp/%s' % filename

        get_file = ('wget --no-check-certificate -O %(file_location)s '
                    'https://landfill.addons.allizom.org/db/%(filename)s' % {
                        'file_location': file_location,
                        'filename': filename,
                    })
        load_dump = 'gzcat %s' % file_location
        write_dump = 'mysql -u%(db_user)s %(db_name)s' % {
            'db_user': settings.DATABASES['default']['USER'],
            'db_name': settings.DATABASES['default']['NAME'],
        }

        if kw['no_download']:
            if os.path.exists(file_location):
                print('Skipping landfill download and using %s' % file_location)
            else:
                print('No file for the current day')
                print('expected: %s' % file_location)
                return
        else:
            print('Removing existing landfill file before downloading')
            print('Downloading landfill file.')
            download_process = Popen(shlex.split(get_file))
            download_process.wait()

        print('Piping file into mysql.')
        loader_process = Popen(shlex.split(load_dump),
                               stdout=PIPE)
        writer_process = Popen(shlex.split(write_dump),
                               stdin=loader_process.stdout)
        writer_process.wait()
        if kw['no_notice']:
            print('Removing landfile site notice.')
            Config.objects.filter(key='site_notice').delete()
