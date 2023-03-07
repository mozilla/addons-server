# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia import amo
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.files.models import File
from olympia.files.tasks import extract_host_permissions


class Command(BaseCommand):
    help = 'Extract host permissions from manifests in stored xpis.'

    def handle(self, *args, **options):
        log = olympia.core.logger.getLogger('z.files')
        files = File.objects.filter(version__addon__type=amo.ADDON_EXTENSION).order_by(
            'pk'
        )
        pks = list(files.values_list('pk', flat=True))

        log.info(
            'Using %s file pks to extract host permissions, max pk: %s'
            % (len(pks), pks[-1])
        )
        if pks:
            chunked_tasks = create_chunked_tasks_signatures(
                extract_host_permissions, pks, chunk_size=100
            )
            chunked_tasks.apply_async()
