from datetime import datetime
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

import commonware.log

from addons.models import File
# TODO: use DownloadCount when the script is proven to work correctly.
from stats.models import update_inc, DownloadCountTmp as DownloadCount


log = commonware.log.getLogger('adi.downloadcountsfromfile')


class Command(BaseCommand):
    """Update download count metrics from a file in the database.

    Usage:
    ./manage.py download_counts_from_file <filename> --date=YYYY-MM-DD


    We get a row for each "addon download" request, in this format:

        <count> <addon id> <click source>

    There is one DownloadCount entry per addon per day, and each field holds
    the json-ified dict of keys/counters.

    Eg, for the above request:

        addon: <the addon that has this id>
        count: <the number of requests for this addon, for this day>
        date: <the date of the day the queries were made>
        src: {'dp-btn-primary': 1}

    """
    help = __doc__

    option_list = BaseCommand.option_list + (
        make_option('--date', action='store', type='string',
                    dest='date', help='Date in the YYYY-MM-DD format.'),
        make_option('--separator', action='store', type='string', default='\t',
                    dest='separator', help='Field separator in file.'),
    )

    def handle(self, *args, **options):
        start = datetime.now()  # Measure the time it takes to run the script.
        day = options['date']
        if not day:
            raise CommandError('You must specify a --date parameter in the '
                               ' YYYY-MM-DD format.')
        sep = options['separator']
        filename = args[0]
        # First, make sure we don't have any existing counts for the same day,
        # or it would just increment again the same data.
        DownloadCount.objects.filter(date=day).delete()

        # Memoize the files to addon relations and the DownloadCounts.
        download_counts = {}
        # Perf: preload all the files once and for all.
        # This builds a dict where each key (the file_id we get from the hive
        # query) has the addon_id as value.
        files_to_addon = dict(File.objects.values_list('id',
                                                       'version__addon_id'))

        with open(filename) as count_file:
            for index, line in enumerate(count_file):
                if index and (index % 10000) == 0:
                    log.info('Processed %s lines' % index)

                splitted = line[:-1].split(sep)

                if len(splitted) != 3:
                    log.debug('Badly formatted row: %s' % line)
                    continue

                counter, file_id, src = splitted
                try:
                    file_id, counter = int(file_id), int(counter)
                except ValueError:  # Badly formatted? Drop.
                    continue

                # Does this file exist?
                if file_id in files_to_addon:
                    addon_id = files_to_addon[file_id]
                else:
                    log.info('File with id: %s not found' % file_id)
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

        # Create in bulk: this is much faster.
        DownloadCount.objects.bulk_create(download_counts.values(), 100)
        total_time = (datetime.now() - start).total_seconds()
        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s seconds' % total_time)
