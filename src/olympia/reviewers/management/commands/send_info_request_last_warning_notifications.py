# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.utils import notify_about_activity_log
from olympia.addons.models import Addon
from olympia.users.notifications import reviewer_reviewed


class Command(BaseCommand):
    help = 'Notify developers with pending info requests about to expire'

    def handle(self, *args, **options):
        # Fetch addons with request for information expiring in one day.
        one_day_in_the_future = datetime.now() + timedelta(days=1)
        qs = Addon.objects.filter(
            addonreviewerflags__notified_about_expiring_info_request=False,
            addonreviewerflags__pending_info_request__lt=one_day_in_the_future)
        for addon in qs:
            # The note we need to send the mail should always going to be the
            # last information request, as making a new one extends the
            # deadline.
            note = ActivityLog.objects.for_addons(addon).filter(
                action=amo.LOG.REQUEST_INFORMATION.id).latest('pk')
            version = note.versionlog_set.latest('pk').version
            log.info(
                'Notifying developers of %s about expiring info request',
                addon.pk)
            # This re-sends the notification sent when the information was
            # requested, but with the new delay in the body of the email now
            # that the notification is about to expire.
            notify_about_activity_log(
                addon, version, note, perm_setting=reviewer_reviewed.short,
                send_to_reviewers=False, send_to_staff=False)
            addon.addonreviewerflags.update(
                notified_about_expiring_info_request=True)
