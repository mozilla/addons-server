import codecs
from datetime import datetime, timedelta
from optparse import make_option
from os import path, unlink

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import commonware.log

import amo
from addons.models import Addon
from stats.models import update_inc, UpdateCount

from . import get_date_from_file


log = commonware.log.getLogger('adi.updatecountsfromfile')


class Command(BaseCommand):
    """Process hive results stored in different files and store them in the db.

    Usage:
    ./manage.py update_counts_from_file <folder> --date=YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is `hive_results/<YYYY-MM-DD>/`.
    This folder will be located in `<settings.NETAPP_STORAGE>/tmp`.

    Five files are processed:
    - update_counts_by_version.hive
    - update_counts_by_status.hive
    - update_counts_by_app.hive
    - update_counts_by_os.hive
    - update_counts_by_locale.hive

    Each file has the following cols:
    - date
    - addon guid
    - data: the data grouped on (eg version, status...).
    - count
    - update type

    For the "app" file, the "data" col is in fact two cols: the application
    guid and the application version.

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
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        folder = args[0] if args else 'hive_results'
        folder = path.join(settings.TMP_PATH, folder, day)
        sep = options['separator']
        groups = ('version', 'status', 'app', 'os', 'locale')
        group_filepaths = []
        # Make sure we're not trying to update with mismatched data.
        for group in groups:
            filepath = path.join(folder, 'update_counts_by_%s.hive' % group)
            if get_date_from_file(filepath, sep) != day:
                raise CommandError('%s file contains data for another day' %
                                   filepath)
            group_filepaths.append((group, filepath))
        # First, make sure we don't have any existing counts for the same day,
        # or it would just increment again the same data.
        UpdateCount.objects.filter(date=day).delete()

        # Memoize the addons and the UpdateCounts.
        update_counts = {}
        # Perf: preload all the addons once and for all.
        # This builds a dict where each key (the addon guid we get from the
        # hive query) has the addon_id as value.
        guids_to_addon = (dict(Addon.objects.exclude(guid__isnull=True)
                                            .exclude(type=amo.ADDON_PERSONA)
                                            .values_list('guid', 'id')))

        index = -1
        for group, filepath in group_filepaths:
            with codecs.open(filepath, encoding='utf8') as results_file:
                for line in results_file:
                    index += 1
                    if index and (index % 1000000) == 0:
                        log.info('Processed %s lines' % index)

                    splitted = line[:-1].split(sep)

                    if ((group == 'app' and len(splitted) != 6)
                            or (group != 'app' and len(splitted) != 5)):
                        log.debug('Badly formatted row: %s' % line)
                        continue

                    if group == 'app':
                        day, addon_guid, app_id, app_ver, count, \
                            update_type = splitted
                    else:
                        day, addon_guid, data, count, update_type = splitted

                    addon_guid = addon_guid.strip()
                    if update_type:
                        update_type.strip()

                    # Old versions of Firefox don't provide the update type.
                    # All the following are "empty-like" values.
                    if update_type in ['0', 'NULL', 'None', '', '\N',
                                       '%UPDATE_TYPE%']:
                        update_type = None

                    try:
                        count = int(count)
                        if update_type:
                            update_type = int(update_type)
                    except ValueError:  # Badly formatted? Drop.
                        continue

                    # The following is magic that I don't understand. I've just
                    # been told that this is the way we can make sure a request
                    # is valid:
                    # > the lower bits for updateType (eg 112) should add to
                    # > 16, if not, ignore the request.
                    # > udpateType & 31 == 16 == valid request.
                    if update_type and update_type & 31 != 16:
                        log.debug("Update type doesn't add to 16: %s" %
                                  update_type)
                        continue

                    # Does this addon exist?
                    if addon_guid and addon_guid in guids_to_addon:
                        addon_id = guids_to_addon[addon_guid]
                    else:
                        log.debug(u"Addon {guid} doesn't exist."
                                  .format(guid=addon_guid.strip()))
                        continue

                    # Memoize the UpdateCount.
                    if addon_guid in update_counts:
                        uc = update_counts[addon_guid]
                    else:
                        uc = UpdateCount(date=day, addon_id=addon_id, count=0)
                        update_counts[addon_guid] = uc

                    # We can now fill the UpdateCount object.
                    if group == 'version':
                        # Take this count as the global number of daily users.
                        uc.count += count
                        uc.versions = update_inc(uc.versions, data, count)
                    elif group == 'status':
                        uc.statuses = update_inc(uc.statuses, data, count)
                    elif group == 'app':
                        # Applications is a dict of dicts, eg:
                        # {"{ec8030f7-c20a-464f-9b0e-13a3a9e97384}":
                        #       {"10.0": 2, "21.0": 1, ....},
                        #  "some other application guid": ...
                        # }
                        if uc.applications is None:
                            uc.applications = {}
                        app = uc.applications.get(app_id, {})
                        # Now overwrite this application's dict with
                        # incremented counts for its versions.
                        uc.applications.update(
                            {app_id: update_inc(app, app_ver, count)})
                    elif group == 'os':
                        uc.oses = update_inc(uc.oses, data, count)
                    elif group == 'locale':
                        # Drop incorrect locales sizes.
                        if len(data) > 10:
                            continue
                        uc.locales = update_inc(uc.locales, data, count)

        # Create in bulk: this is much faster.
        UpdateCount.objects.bulk_create(update_counts.values(), 100)
        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s' % (datetime.now() - start))

        # Clean up files.
        for _, filepath in group_filepaths:
            log.debug('Deleting {path}'.format(path=filepath))
            unlink(filepath)
