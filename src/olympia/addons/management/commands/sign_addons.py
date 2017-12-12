# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from olympia.lib.crypto.tasks import sign_addons


class Command(BaseCommand):
    help = 'Sign a list of addons.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('addon_id', nargs='*')
        parser.add_argument(
            '--signing-server', action='store', type=str,
            dest='signing_server',
            help='The signing server to use for full reviews.')

        parser.add_argument(
            '--force', action='store_true', dest='force',
            help='Sign the addon if it is already signed.')

        parser.add_argument(
            '--reason', action='store', type=str, dest='reason',
            help='The reason for the resign that we will send '
                 'the developer.')

    def handle(self, *args, **options):
        if len(options['addon_id']) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to sign. If you want to '
                'sign them all, use the "process_addons --task sign_addons" '
                'management command.')

        full_server = options.get('signing_server') or settings.SIGNING_SERVER

        addon_ids = [int(addon_id) for addon_id in options['addon_id']]
        with override_settings(
                SIGNING_SERVER=full_server):
            sign_addons(
                addon_ids, force=options['force'], reason=options['reason'])
