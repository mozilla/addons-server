from datetime import datetime, timedelta
from os import path, unlink

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.files.models import File
from olympia.stats.models import DownloadCount, update_inc

from . import get_date, get_stats_data, save_stats_to_file


log = olympia.core.logger.getLogger('adi.downloadcounts')


def is_valid_source(src, fulls, prefixes):
    """Return True if the source is valid.

    A source is valid if it is in the list of valid full sources or prefixed by
    a prefix in the list of valid prefix sources.

    """
    return src in fulls or any(p in src for p in prefixes)


class Command(BaseCommand):
    """Update download count metrics from stats_source in the database.

    Usage:
    ./manage.py download_counts_from_file \
        <folder> --date=YYYY-MM-DD --stats_source={s3,file}

    If no date is specified, the default is the day before.

    If no stats_source is specified, the default is set to s3.

    If stats_source is file:
        If not folder is specified, the default is `hive_results/YYYY-MM-DD/`.
        This folder will be located in `<settings.NETAPP_STORAGE>/tmp`.

    If stats_source is s3:
        This file will be located in
            `<settings.AWS_STATS_S3_BUCKET>/amo_stats`.

        File processed:
        - download_counts/YYYY-MM-DD/000000_0

    We get a row for each "addon download" request, in this format:

        <count> <file id or add-on id or add-on slug> <click source>

    We insert one DownloadCount entry per addon per day, and each row holds
    the json-ified dict of click sources/counters.

    Eg, for the above request:

        date: <the date of the day the queries were made>
        count: <the number of requests for this addon, for this day>
        addon: <the addon that has this id>
        src: {'dp-btn-primary': 1}

    """
    help = __doc__

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('folder_name', default='hive_results', nargs='?')
        parser.add_argument(
            '--stats_source', default='s3',
            choices=['s3', 'file'],
            help='Source of stats data')
        parser.add_argument(
            '--date', action='store', type=str,
            dest='date', help='Date in the YYYY-MM-DD format.')
        parser.add_argument(
            '--separator', action='store', type=str, default='\t',
            dest='separator', help='Field separator in file.')

    def handle(self, *args, **options):
        start = datetime.now()  # Measure the time it takes to run the script.
        day = options['date']
        if not day:
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        sep = options['separator']

        if options['stats_source'] == 's3':
            filepath = 's3://' + '/'.join([settings.AWS_STATS_S3_BUCKET,
                                           'amo_stats', 'download_counts',
                                           day, '000000_0'])

        elif options['stats_source'] == 'file':
            folder = options['folder_name']
            folder = path.join(settings.TMP_PATH, folder, day)
            filepath = path.join(folder, 'download_counts.hive')

        # Make sure we're not trying to update with mismatched data.
        if get_date(filepath, sep) != day:
            raise CommandError('%s file contains data for another day' %
                               filepath)

        # First, make sure we don't have any existing counts for the same day,
        # or it would just increment again the same data.
        DownloadCount.objects.filter(date=day).delete()

        # Memoize the files to addon relations and the DownloadCounts.
        download_counts = {}
        # Perf: preload all the files and slugs once and for all.
        # This builds two dicts:
        # - One where each key (the file_id we get from the hive query) has
        #   the addon_id as value.
        # - One where each key (the add-on slug) has the add-on_id as value.
        files_to_addon = dict(File.objects.values_list('id',
                                                       'version__addon_id'))
        slugs_to_addon = dict(Addon.objects.public().values_list('slug', 'id'))

        # Only accept valid sources, which are constants. The source must
        # either be exactly one of the "full" valid sources, or prefixed by one
        # of the "prefix" valid sources.
        fulls = amo.DOWNLOAD_SOURCES_FULL
        prefixes = amo.DOWNLOAD_SOURCES_PREFIX

        count_file = get_stats_data(filepath)
        for index, line in enumerate(count_file):
            if index and (index % 1000000) == 0:
                log.info('Processed %s lines' % index)

            splitted = line[:-1].split(sep)

            if len(splitted) != 4:
                log.debug('Badly formatted row: %s' % line)
                continue

            day, counter, id_or_slug, src = splitted
            try:
                # Clean up data.
                id_or_slug = id_or_slug.strip()
                counter = int(counter)
            except ValueError:
                # Ignore completely invalid data.
                continue

            if id_or_slug.strip().isdigit():
                # If it's a digit, then it should be a file id.
                try:
                    id_or_slug = int(id_or_slug)
                except ValueError:
                    continue

                # Does this file exist?
                if id_or_slug in files_to_addon:
                    addon_id = files_to_addon[id_or_slug]
                # Maybe it's an add-on ?
                elif id_or_slug in files_to_addon.values():
                    addon_id = id_or_slug
                else:
                    # It's an integer we don't recognize, ignore the row.
                    continue
            else:
                # It's probably a slug.
                if id_or_slug in slugs_to_addon:
                    addon_id = slugs_to_addon[id_or_slug]
                else:
                    # We've exhausted all possibilities, ignore this row.
                    continue

            if not is_valid_source(src, fulls=fulls, prefixes=prefixes):
                continue

            # Memoize the DownloadCount.
            if addon_id in download_counts:
                dc = download_counts[addon_id]
            else:
                dc = DownloadCount(date=day, addon_id=addon_id, count=0)
                download_counts[addon_id] = dc

            # We can now fill the DownloadCount object.
            dc.count += counter
            dc.sources = update_inc(dc.sources, src, counter)

        # Close all old connections in this thread before we start creating the
        # `DownloadCount` values.
        # https://github.com/mozilla/addons-server/issues/6886
        # If the calculation above takes too long it might happen that we run
        # into `wait_timeout` problems and django doesn't reconnect properly
        # (potentially because of misconfiguration).
        # Django will re-connect properly after it notices that all
        # connections are closed.
        close_old_connections()

        # Create in bulk: this is much faster.
        DownloadCount.objects.bulk_create(download_counts.values(), 100)

        for download_count in download_counts.values():
            save_stats_to_file(download_count)

        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s' % (datetime.now() - start))

        if options['stats_source'] == 'file':
            # Clean up file.
            log.debug('Deleting {path}'.format(path=filepath))
            unlink(filepath)
