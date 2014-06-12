from datetime import datetime
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

import commonware.log

from addons.models import Addon
# TODO: use UpdateCount when the script is proven to work correctly.
from stats.models import update_inc, UpdateCountTmp as UpdateCount


log = commonware.log.getLogger('adi.updatecountsfromfile')


class Command(BaseCommand):
    """Update check versions count metrics from a file in the database.

    Usage:
    ./manage.py update_counts_from_file <filename> --date=YYYY-MM-DD


    We get a row for each "version check" request, in this format:

        <count> <guid> <version> <statuses> <app> <app version> <os> <locale>

    There is one UpdateCount entry per addon per day, and each field holds the
    json-ified dict of keys/counters.

    Eg, for the above request:

        addon: <the addon that has the guid "id">
        count: <the number of requests for this addon, for this day>
        date: <the date of the day the queries were made>
        versions: {'0.6.2': 1}
        statuses: {'userDisabled': 1, 'incompatible': 1}
        applications (app and app version):
            {'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': {'20.0': 1}}
        oses: {'Darwin': 1}
        locales: {'en-US': 1}

    The "applications" field is the most complicated to deal with, because it's
    a dict of dicts: each key of the dict (the application guid) has a value of
    a dict of versions of this application, and the count.

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
        UpdateCount.objects.filter(date=day).delete()

        # Memoize the addons and the UpdateCounts.
        update_counts = {}
        # Perf: preload all the addons once and for all.
        # This builds a dict where each key (the addon guid we get from the
        # hive query) has the addon_id as value.
        guids_to_addon = dict(Addon.objects.values_list('guid', 'id'))

        with open(filename) as count_file:
            for index, line in enumerate(count_file):
                if index and (index % 10000) == 0:
                    log.info('Processed %s lines' % index)

                splitted = line[:-1].split(sep)

                if len(splitted) != 8:
                    log.debug('Badly formatted row: %s' % line)
                    continue

                counter, addon_guid, version, status, app_id, version, \
                    app_os, locale, update_type = splitted
                try:
                    counter = int(counter)
                except ValueError:  # Badly formatted? Drop.
                    continue

                # The following is magic that I don't understand. I've just
                # been told that this is the way we can make sure a request is
                # valid:
                # > the lower bits for updateType=112 should add to 16, if not,
                # > ignore the request. udpateType & 31 == 16 == valid request.
                # The 8th column is the updateType this quote is talking about.
                try:
                    if int(update_type) & 31 == 16:
                        continue
                except:
                    continue

                # We may have several statuses in the same field.
                statuses = status.split(',')

                # Does this addon exit?
                if addon_guid in guids_to_addon:
                    addon_id = guids_to_addon[addon_guid]
                else:
                    log.info('Addon with guid: %s not found' % addon_guid)
                    continue

                # Memoize the UpdateCount.
                if addon_guid in update_counts:
                    uc = update_counts[addon_guid]
                else:
                    uc = UpdateCount(date=day, addon_id=addon_id, count=0)
                    update_counts[addon_guid] = uc

                # We can now fill the UpdateCount object.
                uc.count += counter
                uc.versions = update_inc(uc.versions, version, counter)

                # Applications is a dict of dicts, eg:
                # {"{ec8030f7-c20a-464f-9b0e-13a3a9e97384}":  # Firefox.
                #       {"10.0": 2, "21.0": 1, ....},
                #  "some other application guid": ...
                # }
                if uc.applications is None:
                    uc.applications = {}
                app = uc.applications.get(app_id, {})
                # Now overwrite this application's dict with incremented
                # counts for its versions.
                uc.applications.update(
                    {app_id: update_inc(app, version, counter)})

                uc.oses = update_inc(uc.oses, app_os, counter)
                uc.locales = update_inc(uc.locales, locale, counter)

                # We may have received a list of more than one status.
                for status in statuses:
                    uc.statuses = update_inc(uc.statuses, status, counter)

        # Create in bulk: this is much faster.
        UpdateCount.objects.bulk_create(update_counts.values(), 100)
        total_time = (datetime.now() - start).total_seconds()
        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s seconds' % total_time)
