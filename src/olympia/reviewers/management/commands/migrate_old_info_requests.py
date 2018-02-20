# -*- coding: utf-8 -*-
from datetime import datetime

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.addons.models import AddonReviewerFlags
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.reviewers.migrate_old_info_requests')


class Command(BaseCommand):
    help = 'Notify developers with pending info requests about to expire'

    def handle(self, *args, **options):
        deadline = datetime.now()
        qs = Version.objects.no_cache().raw(
            'SELECT id, addon_id, version FROM versions '
            'WHERE has_info_request = true '
            'GROUP BY addon_id')
        for version in qs:
            addon = version.addon
            log.info('Migrating flag for addon %d', addon.pk)
            AddonReviewerFlags.objects.update_or_create(addon=addon, defaults={
                # notified_about_expiring_info_request is set to True to avoid
                # sending notifications for this info request, since it's an
                # old one.
                'notified_about_expiring_info_request': True,
                'pending_info_request': deadline,
            })
