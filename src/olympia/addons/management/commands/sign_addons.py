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
            '--force',
            action='store_true',
            dest='force',
            help='Sign the addon if it is already signed.',
        )

        parser.add_argument(
            '--reason',
            action='store',
            type=str,
            dest='reason',
            help='The reason for the resign that we will send '
            'the developer.',
        )

        parser.add_argument(
            '--autograph-server-url',
            action='store',
            type=str,
            dest='autograph_server_url',
            help='The optional server URL for the autograph signing server.',
        )

        parser.add_argument(
            '--autograph-user-id',
            action='store',
            type=str,
            dest='autograph_user_id',
            help='The optional user id for the autograph signing server.',
        )

        parser.add_argument(
            '--autograph-key',
            action='store',
            type=str,
            dest='autograph_key',
            help='The optional key for the autograph signing server.',
        )

        parser.add_argument(
            '--autograph-signer',
            action='store',
            type=str,
            dest='autograph_signer',
            help='The optional signer for the autograph signing server.',
        )

    def handle(self, *args, **options):
        if len(options['addon_id']) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to sign. If you want to '
                'sign them all, use the "process_addons --task sign_addons" '
                'management command.'
            )

        defaults = settings.AUTOGRAPH_CONFIG

        def _get_option_or_default(key):
            return options.get('autograph_{}'.format(key), defaults[key])

        autograph_config = {
            'server_url': _get_option_or_default('server_url'),
            'user_id': _get_option_or_default('user_id'),
            'key': _get_option_or_default('key'),
            'signer': _get_option_or_default('signer'),
        }

        with override_settings(AUTOGRAPH_CONFIG=autograph_config):
            addon_ids = [int(addon_id) for addon_id in options['addon_id']]
            sign_addons(
                addon_ids, force=options['force'], reason=options['reason']
            )
