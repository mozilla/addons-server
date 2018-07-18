# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.files.models import WebextPermissionDescription
from olympia.files.tasks import update_webext_descriptions_all


class Command(BaseCommand):
    help = (
        'Download and update webextension permission descriptions from '
        'mozilla-central.'
    )

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--clear',
            action='store_true',
            dest='clear',
            default=False,
            help='Clear existing descriptions in the database first.',
        )

    def handle(self, *args, **options):
        if options['clear']:
            WebextPermissionDescription.objects.all().delete()

        central_url = settings.WEBEXT_PERM_DESCRIPTIONS_URL
        locales_url = settings.WEBEXT_PERM_DESCRIPTIONS_LOCALISED_URL
        amo_locales = [
            l
            for l in settings.AMO_LANGUAGES
            if l not in ('en-US', 'dbg', 'dbr', 'dbl')
        ]
        # Fetch canonical en-US descriptions first; then l10n after.
        update_webext_descriptions_all.apply_async(
            args=[
                (central_url, 'en-US'),
                [
                    (locales_url.format(locale=locale), locale)
                    for locale in amo_locales
                ],
            ]
        )
