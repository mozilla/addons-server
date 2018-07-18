# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from celery import group

from olympia.amo.utils import chunked
from olympia.files.models import File
from olympia.files.tasks import extract_webext_permissions


class Command(BaseCommand):
    help = 'Extract webextension permissions from manifests in stored xpis.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            default=False,
            help='Extract from Files that already have permissions.',
        )

    def handle(self, *args, **options):
        files = File.objects.filter(is_webextension=True)
        if not options['force']:
            files = files.filter(_webext_permissions=None)
        pks = files.values_list('pk', flat=True)
        print('pks count %s' % pks.count())
        if pks:
            grouping = []
            for chunk in chunked(pks, 100):
                grouping.append(
                    extract_webext_permissions.subtask(args=[chunk])
                )

            ts = group(grouping)
            ts.apply_async()
