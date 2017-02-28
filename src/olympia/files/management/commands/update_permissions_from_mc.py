# -*- coding: utf-8 -*-
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand

from celery import chain

from olympia.files.models import WebextPermissionDescription
from olympia.files.tasks import update_webext_descriptions


class Command(BaseCommand):
    help = ('Download and update webextension permission descriptions from '
            'mozilla-central.')
    option_list = BaseCommand.option_list + (
        make_option('--clear', action='store_true', dest='clear',
                    help='Clear existing descriptions in the database first'),
    )

    def handle(self, *args, **options):
        if options['clear']:
            WebextPermissionDescription.objects.all().delete()

        central_url = settings.WEBEXT_PERM_DESCRIPTIONS_URL
        locales_url = settings.WEBEXT_PERM_DESCRIPTIONS_LOCALISED_URL
        # Fetch canonical en-US descriptions first; then l10n after.
        tasks = [update_webext_descriptions.s(central_url)] + [
            update_webext_descriptions.si(
                locales_url.format(locale=locale),
                locale=locale, create=False)
            for locale in settings.AMO_LANGUAGES]
        chain(tasks)()
