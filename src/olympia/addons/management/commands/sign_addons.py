# -*- coding: utf-8 -*-
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from olympia.lib.crypto.tasks import sign_addons


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = 'Sign a list of addons.'
    option_list = BaseCommand.option_list + (
        make_option('--signing-server', action='store', type='string',
                    dest='signing_server',
                    help='The signing server to use for full reviews'),
        make_option('--force', action='store_true', dest='force',
                    help='Sign the addon if it is already signed'),
        make_option('--reason', action='store', type='string', dest='reason',
                    help='The reason for the resign that we will send '
                         'the developer.')
    )

    def handle(self, *args, **options):
        if len(args) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to sign. If you want to '
                'sign them all, use the "process_addons --task sign_addons" '
                'management command.')
        full_server = options.get('signing_server') or settings.SIGNING_SERVER

        addon_ids = [int(addon_id) for addon_id in args]
        with override_settings(
                SIGNING_SERVER=full_server):
            sign_addons(
                addon_ids, force=options['force'], reason=options['reason'])
