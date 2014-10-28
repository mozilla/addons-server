# -*- coding: utf-8 -*-
import sys

from django.core.management.base import BaseCommand, CommandError

from addons.models import Addon


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = 'Sign a list of addons'

    def handle(self, *args, **options):
        if len(args) == 0:
            raise CommandError('Please provide at least one addon ID')

        for addon_id in args:
            if not addon_id.isdigit():
                sys.stderr.write(
                    'Warning: Addon ID should be an integer (%s).\n'
                    % addon_id)
                continue

            try:
                addon = Addon.objects.get(pk=int(addon_id))
            except Addon.DoesNotExist:
                sys.stderr.write(
                    'Warning: Addon %s does not exist.\n'
                    % addon_id)
                continue

            for version in addon.versions.all():
                addon.sign_version_files(version.pk)
