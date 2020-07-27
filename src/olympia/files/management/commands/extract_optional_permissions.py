# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from olympia import amo
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.files.models import File
from olympia.files.tasks import extract_optional_permissions


class Command(BaseCommand):
    help = 'Extract optional permissions from manifests in stored xpis.'

    def handle(self, *args, **options):
        files = File.objects.filter(
            is_webextension=True, version__addon__type=amo.ADDON_EXTENSION
        ).order_by('pk')
        pks = files.values_list('pk', flat=True)
        print('pks count %s' % pks.count())
        if pks:
            chunked_tasks = create_chunked_tasks_signatures(
                extract_optional_permissions, list(pks), chunk_size=100)
            chunked_tasks.apply_async()
