# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.utils import chunked
from olympia.reviewers.utils import ReviewHelper


class Command(BaseCommand):
    help = u'Approve a list of add-ons, given their GUIDs.'

    def add_arguments(self, parser):
        parser.add_argument('addon_guid', nargs='+')

    def handle(self, *args, **options):
        confirm = raw_input(
            u'Are you sure you want to bulk approve and sign all those {0} '
            u'addons? (yes/no)'.format(len(args)))
        if confirm != 'yes':
            raise CommandError(u'Aborted.')

        for chunk in chunked(options['addon_guid'], 100):
            files = get_files(chunk)
            log.info(u'Bulk approving chunk of %s files', len(files))

            files_with_review_type = [
                (file_, get_review_type(file_)) for file_ in files]

            approve_files(files_with_review_type)


def get_files(addon_guids):
    """Return the list of files that need approval, given a list of GUIDs.

    A file needs approval if it's unreviewed.
    """
    # Get all the add-ons that have a GUID from the list, and which are either
    # reviewed or awaiting a review.
    addons = Addon.objects.filter(
        guid__in=addon_guids,
        status__in=amo.VALID_ADDON_STATUSES)
    # Of all those add-ons, we return the list of latest version files that are
    # under review, or add-ons that are under review.
    files = []
    for addon in addons:
        files += addon.find_latest_version(
            amo.RELEASE_CHANNEL_LISTED).unreviewed_files
    return files


def approve_files(files_with_review_type):
    """Approve the files waiting for review (and sign them)."""
    for file_, review_type in files_with_review_type:
        version = file_.version
        addon = version.addon
        helper = ReviewHelper(request=None, addon=addon,
                              version=file_.version)
        # Provide the file to review/sign to the helper.
        helper.set_data({'addon_files': [file_],
                         'comments': u'bulk approval'})
        if review_type == 'full':
            # Already approved, or waiting for a full review.
            helper.handler.process_public()
            log.info(u'File %s (addon %s) approved', file_.pk, addon.pk)
        else:
            log.info(u'File %s (addon %s) not approved: '
                     u'addon status: %s, file status: %s',
                     file_.pk, addon.pk, addon.status, file_.status)


def get_review_type(file_):
    """Return 'full' or None depending on the file/addon status."""
    addon_status = file_.version.addon.status
    if addon_status == amo.STATUS_NOMINATED or (
            addon_status == amo.STATUS_PUBLIC and
            file_.status == amo.STATUS_AWAITING_REVIEW):
        # Add-on or file is waiting for a full review.
        return 'full'
