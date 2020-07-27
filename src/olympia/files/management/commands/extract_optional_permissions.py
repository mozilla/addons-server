# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from celery import group

from olympia import amo
from olympia.amo.utils import chunked
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
            grouping = []
            for chunk in chunked(pks, 100):
                grouping.append(
                    extract_optional_permissions.subtask(args=[chunk]))

            ts = group(grouping)
            ts.apply_async()
