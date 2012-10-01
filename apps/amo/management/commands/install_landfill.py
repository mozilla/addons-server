from datetime import date
from gzip import GzipFile
from optparse import make_option
import os
import shlex
from StringIO import StringIO
from subprocess import Popen, PIPE

import requests

from django.conf import settings
from django.core.management.base import BaseCommand

import requests

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
        make_option('--no-save-file',
                    action='store_true',
                    dest='no_save_file',
                    default=False,
                    help='Do not save the file downloaded from allizom.'),
        )

    def handle(self, *args, **kw):
        filename = date.today().strftime('landfill-%Y-%m-%d.sql.gz')
        file_location = '/tmp/%s' % filename
        file_url = 'https://landfill.addons.allizom.org/db_data/%s' % filename

        write_dump = 'mysql -u%(db_user)s %(db_name)s' % {
            'db_user': settings.DATABASES['default']['USER'],
            'db_name': settings.DATABASES['default']['NAME'],
        }

        db_password = settings.DATABASES['default'].get('PASSWORD')
        if db_password:
            write_dump += ' -p%s' % db_password

        if kw['no_download']:
            if os.path.exists(file_location):
                print('Skipping landfill download and using %s' % file_location)
                landfill_file = GzipFile(filename=file_location,
                                         mode='rb').read()
            else:
                print('No file for the current day')
                print('expected: %s' % file_location)
                return
        else:
            print('Downloading landfill file: %s' % file_url)
            gzipped_file = requests.get(file_url, verify=False).content
            landfill_file = GzipFile(
                fileobj=StringIO(gzipped_file),
                mode='rb').read()

        if not kw['no_save_file']:
            if os.path.exists(file_location):
                print('File already exists not overwriting: %s' % file_location)
            else:
                with open(file_location, 'wb') as f:
                    print('Saving file to %s' % file_location)
                    f.write(gzipped_file)
        print('Piping file into mysql.')
        writer_process = Popen(
            shlex.split(write_dump),
            stdin=PIPE)
        writer_process.communicate(input=landfill_file)
        writer_process.wait()
        if kw['no_notice']:
            print('Removing landfile site notice.')
            Config.objects.filter(key='site_notice').delete()
