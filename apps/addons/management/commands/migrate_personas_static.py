from optparse import make_option
import os
from os.path import join, exists
import shutil

from django.core.management.base import BaseCommand

from addons.models import Persona


class Command(BaseCommand):
    help = ('Copy static files for personas from getpersonas.com to the AMO '
            'static files directory. The directory name for each persona '
            'will be renamed from its persona ID to its addon ID.')
    option_list = BaseCommand.option_list + (
        make_option('--personas-dir', dest='personas_dir',
                    help='Root directory of getpersonas static files.'),
        make_option('--addons-dir', dest='amo_dir',
                    help='Directory of AMO static files.'))

    def handle(self, *args, **options):
        if 'personas_dir' not in options:
            print "Needs --personas-dir."
            return
        if 'addons_dir' not in options:
            print "Needs --addons-dir."
            return
        mapping = dict(Persona.objects.values_list('pk', 'addon_id'))
        for first in os.listdir(options['personas_dir']):
            if not first.isdigit():
                continue
            second_path = join(options['personas_dir'], first)
            for second in os.listdir(second_path):
                third_path = join(second_path, second)
                for persona_id in os.listdir(third_path):
                    persona = join(third_path, persona_id)
                    target = join(options['amo_dir'],
                                  str(mapping[int(persona_id)]))
                    if exists(target):
                        continue
                    print "%s --> %s" % (persona, target)
                    shutil.copytree(persona, target)
