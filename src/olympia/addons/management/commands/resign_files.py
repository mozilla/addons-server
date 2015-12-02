# -*- coding: utf-8 -*-
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from amo.utils import chunked
from lib.crypto.tasks import resign_files


class Command(BaseCommand):
    args = '<file_id file_id ...>'
    help = 'Resign a list of already signed files.'
    option_list = BaseCommand.option_list + (
        make_option('--signing-server', action='store', type='string',
                    dest='signing_server',
                    help='The signing server to use for full reviews'),
        make_option('--preliminary-signing-server', action='store',
                    type='string',
                    dest='preliminary_signing_server',
                    help='The signing server to use for preliminary reviews'),
    )

    def handle(self, *args, **options):
        if len(args) == 0:
            raise CommandError('Please provide at least one file id to resign')
        full_server = options.get('signing_server') or settings.SIGNING_SERVER
        prelim_server = (options.get('preliminary_signing_server') or
                         settings.PRELIMINARY_SIGNING_SERVER)

        file_ids = [int(file_id) for file_id in args]
        with override_settings(
                SIGNING_SERVER=full_server,
                PRELIMINARY_SIGNING_SERVER=prelim_server):
            for chunk in chunked(file_ids, 100):
                resign_files.delay(chunk)
