# -*- coding: utf-8 -*-
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from lib.crypto.packaged import sign, SigningError
from versions.models import Version


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = 'Sign a list of addons.'
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
        if len(args) == 0:  # Sign all the addons?
            raise CommandError(
                'Please provide at least one addon id to sign. If you want to '
                'sign them all, use the "process_addons --task sign_addons" '
                'management command.')
        signing_server = options.get('signing_server', settings.SIGNING_SERVER)
        preliminary_signing_server = options.get(
            'preliminary_signing_server', settings.PRELIMINARY_SIGNING_SERVER)

        addon_ids = [int(addon_id) for addon_id in args]
        to_sign = Version.objects.filter(addon_id__in=addon_ids)

        num_versions = to_sign.count()
        self.stdout.write('Starting the signing of %s versions' % num_versions)
        for version in to_sign:
            try:
                self.stdout.write('Signing version %s' % version.pk)
                with override_settings(
                        SIGNING_SERVER=signing_server,
                        PRELIMINARY_SIGNING_SERVER=preliminary_signing_server):
                    sign(version)
            except SigningError as e:
                self.stderr.write(
                    'Error while signing version %s: %s' % (version.pk, e))
