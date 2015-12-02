# -*- coding: utf-8 -*-
import logging

from django.core.management.base import BaseCommand, CommandError

import amo
from addons.models import Addon
from amo.utils import chunked
from editors.helpers import ReviewHelper

log = logging.getLogger('z.addons')


class Command(BaseCommand):
    args = u'<addon_guid addon_guid ...>'
    help = u'Approve a list of add-ons, given their GUIDs.'

    def handle(self, *args, **options):
        if len(args) == 0:  # No GUID provided?
            raise CommandError(
                u'Please provide at least one add-on guid to approve.')

        confirm = raw_input(
            u'Are you sure you want to bulk approve and sign all those {0} '
            u'addons? (yes/no)'.format(len(args)))
        if confirm != 'yes':
            raise CommandError(u'Aborted.')

        for chunk in chunked(args, 100):
            files = get_files(chunk)
            log.info(u'Bulk approving chunk of %s files', len(files))

            files_with_review_type = [
                (file_, get_review_type(file_)) for file_ in files]

            approve_files(files_with_review_type)


def get_files(addon_guids):
    """Return the list of files that need approval, given a list of GUIDs.

    A file needs approval if:
    - it's unreviewed
    - it's preliminary reviewed, but its addon is requesting a full review
    """
    # Get all the add-ons that have a GUID from the list, and which are either
    # reviewed or awaiting a review.
    addons = Addon.with_unlisted.filter(
        guid__in=addon_guids,
        status__in=amo.UNDER_REVIEW_STATUSES + amo.REVIEWED_STATUSES)
    # Of all those add-ons, we return the list of latest_version files that are
    # under review, or add-ons that are under review.
    files = []
    for addon in addons:
        files += addon.latest_version.unreviewed_files
    return files


def approve_files(files_with_review_type):
    """Approve the files (and sign them).

    A file will be fully approved if:
    - it's waiting for a full review
    - it's preliminary reviewed, and its addon is waiting for a full review
    A file will be prelim approved if:
    - it's waiting for a prelim review
    """
    for file_, review_type in files_with_review_type:
        version = file_.version
        addon = version.addon
        helper = ReviewHelper(request=None, addon=addon,
                              version=file_.version)
        # Provide the file to review/sign to the helper.
        helper.set_data({'addon_files': [file_],
                         'comments': u'bulk approval'})
        if review_type == 'full':
            # Already fully reviewed, or waiting for a full review.
            helper.handler.process_public()
            log.info(u'File %s (addon %s) fully reviewed', file_.pk, addon.pk)
        elif review_type == 'prelim':
            # Already prelim reviewed, or waiting for a prelim review.
            helper.handler.process_preliminary()
            log.info(u'File %s (addon %s) prelim reviewed', file_.pk, addon.pk)
        else:
            log.info(u'File %s (addon %s) not reviewed: '
                     u'addon status: %s, file status: %s',
                     file_.pk, addon.pk, addon.status, file_.status)


def get_review_type(file_):
    """Return 'full', 'prelim' or None depending on the file/addon status."""
    addon_status = file_.version.addon.status
    if addon_status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED]:
        # Add-on is waiting for a full review.
        return 'full'
    if addon_status == amo.STATUS_UNREVIEWED:
        # Add-on is waiting for a prelim review.
        return 'prelim'
    if file_.status == amo.STATUS_UNREVIEWED:
        # Addon is reviewed, not file.
        if addon_status == amo.STATUS_PUBLIC:
            return 'full'
        elif addon_status == amo.STATUS_LITE:
            return 'prelim'
