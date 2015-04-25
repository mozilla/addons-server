# -*- coding: utf-8 -*-
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from lib.crypto.tasks import unsign_addons


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = 'Unsign a list of addons.'
    option_list = BaseCommand.option_list + (
        make_option('--force', action='store_true', dest='force',
                    help='Unsign the addon if it is not already signed'),
    )

    def handle(self, *args, **options):
        if len(args) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to unsign. If you want '
                'to unsign them all, use the '
                '"process_addons --task sign_addons" management command.')
        addon_ids = [int(addon_id) for addon_id in args]
        unsign_addons(addon_ids, force=options['force'])
