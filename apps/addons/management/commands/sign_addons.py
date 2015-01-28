# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand, CommandError

from lib.crypto.packaged import sign, SigningError
from versions.models import Version


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = 'Sign a list of addons.'

    def handle(self, *args, **options):
        if len(args) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to sign. If you want to '
                'sign them all, use the "process_addons --task sign_addons" '
                'management command.')

        addon_ids = [int(addon_id) for addon_id in args]
        to_sign = Version.objects.filter(addon_id__in=addon_ids)

        num_versions = to_sign.count()
        self.stdout.write('Starting the signing of %s versions' % num_versions)
        for version in to_sign:
            try:
                self.stdout.write('Signing version %s' % version.pk)
                sign(version)
            except SigningError as e:
                self.stderr.write(
                    'Error while signing version %s: %s' % (version.pk, e))
