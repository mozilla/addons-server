import json
import re

from datetime import datetime, timedelta
from os import path, unlink

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.stats.models import UpdateCount, update_inc

from . import get_date, get_stats_data


log = olympia.core.logger.getLogger('adi.updatecounts')

# Validate a locale: must be like 'fr', 'en-us', 'zap-MX-diiste', ...
LOCALE_REGEX = re.compile(
    r"""^[a-z]{2,3}      # General: fr, en, dsb,...
                              (-[A-Z]{2,3})?   # Region: -US, -GB, ...
                              (-[a-z]{2,12})?$ # Locality: -valencia, -diiste
                          """,
    re.VERBOSE,
)
VALID_STATUSES = [
    "userDisabled,incompatible",
    "userEnabled",
    "Unknown",
    "userDisabled",
    "userEnabled,incompatible",
]
UPDATE_COUNT_TRIGGER = "userEnabled"
VALID_APP_GUIDS = amo.APP_GUIDS.keys()
APPVERSION_REGEX = re.compile(
    r"""^[0-9]{1,3}                # Major version: 2, 35
        \.[0-9]{1,3}([ab][0-9])?   # Minor version + alpha or beta: .0a1, .0b2
        (\.[0-9]{1,3})?$           # Patch version: .1, .23
    """,
    re.VERBOSE,
)


class Command(BaseCommand):
    """Process hive results stored in different files and store them in the db.

    Usage:
    ./manage.py update_counts_from_file \
        <folder> --date=YYYY-MM-DD --stats_source={s3,file}

    If no date is specified, the default is the day before.

    If no stats_source is specified, the default is set to s3.

    If stats_source is file:
        If not folder is specified, the default is
            `hive_results/<YYYY-MM-DD>/`.
        This folder will be located in `<settings.NETAPP_STORAGE>/tmp`.

        Five files are processed:
        - update_counts_by_version.hive
        - update_counts_by_status.hive
        - update_counts_by_app.hive
        - update_counts_by_os.hive
        - update_counts_by_locale.hive

    If stats_source is s3:
        This file will be located in
            `<settings.AWS_STATS_S3_BUCKET>/amo_stats`.

        Five files are processed:
        - update_counts_by_version/YYYY-MM-DD/000000_0
        - update_counts_by_status/YYYY-MM-DD/000000_0
        - update_counts_by_app/YYYY-MM-DD/000000_0
        - update_counts_by_os/YYYY-MM-DD/000000_0
        - update_counts_by_locale/YYYY-MM-DD/000000_0

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

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('folder_name', default='hive_results', nargs='?')
        parser.add_argument(
            '--stats_source',
            default='s3',
            choices=['s3', 'file'],
            help='Source of stats data',
        )
        parser.add_argument(
            '--date',
            action='store',
            type=str,
            dest='date',
            help='Date in the YYYY-MM-DD format.',
        )
        parser.add_argument(
            '--separator',
            action='store',
            type=str,
            default='\t',
            dest='separator',
            help='Field separator in file.',
        )

    def handle(self, *args, **options):
        sep = options['separator']

        start = datetime.now()  # Measure the time it takes to run the script.
        day = options['date']
        if not day:
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        groups = ('app', 'locale', 'os', 'status', 'version')
        group_filepaths = []
        # Make sure we're not trying to update with mismatched data.
        for group in groups:
            if options['stats_source'] == 's3':
                filepath = 's3://' + '/'.join(
                    [
                        settings.AWS_STATS_S3_BUCKET,
                        'amo_stats',
                        'update_counts_by_%s' % group,
                        day,
                        '000000_0',
                    ]
                )

            elif options['stats_source'] == 'file':
                folder = options['folder_name']
                folder = path.join(settings.TMP_PATH, folder, day)
                filepath = path.join(
                    folder, 'update_counts_by_%s.hive' % group
                )

            if get_date(filepath, sep) != day:
                raise CommandError(
                    '%s file contains data for another day' % filepath
                )
            group_filepaths.append((group, filepath))

        # First, make sure we don't have any existing counts for the same day,
        # or it would just increment again the same data.
        UpdateCount.objects.filter(date=day).delete()

        # Memoize the addons and the UpdateCounts.
        update_counts = {}
        # Perf: preload all the addons once and for all.
        # This builds a dict where each key (the addon guid we get from the
        # hive query) has the addon_id as value.
        guids_to_addon = dict(
            Addon.objects.public()
            .exclude(guid__isnull=True)
            .exclude(type=amo.ADDON_PERSONA)
            .values_list('guid', 'id')
        )

        for group, filepath in group_filepaths:
            count_file = get_stats_data(filepath)
            for index, line in enumerate(count_file):
                if index and (index % 1000000) == 0:
                    log.info('Processed %s lines' % index)

                splitted = line[:-1].split(sep)

                if (group == 'app' and len(splitted) != 6) or (
                    group != 'app' and len(splitted) != 5
                ):
                    log.debug('Badly formatted row: %s' % line)
                    continue

                if group == 'app':
                    day, addon_guid, app_id, app_ver, count, update_type = (
                        splitted
                    )
                else:
                    day, addon_guid, data, count, update_type = splitted

                addon_guid = addon_guid.strip()
                if update_type:
                    update_type.strip()

                # Old versions of Firefox don't provide the update type.
                # All the following are "empty-like" values.
                if update_type in [
                    '0',
                    'NULL',
                    'None',
                    '',
                    r'\N',
                    '%UPDATE_TYPE%',
                ]:
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
                    log.debug(
                        "Update type doesn't add to 16: %s" % update_type
                    )
                    continue

                # Does this addon exist?
                if addon_guid and addon_guid in guids_to_addon:
                    addon_id = guids_to_addon[addon_guid]
                else:
                    log.debug(
                        u"Addon {guid} doesn't exist.".format(
                            guid=addon_guid.strip()
                        )
                    )
                    continue

                # Memoize the UpdateCount.
                if addon_guid in update_counts:
                    uc = update_counts[addon_guid]
                else:
                    uc = UpdateCount(date=day, addon_id=addon_id, count=0)
                    update_counts[addon_guid] = uc

                # We can now fill the UpdateCount object.
                if group == 'version':
                    self.update_version(uc, data, count)
                elif group == 'status':
                    self.update_status(uc, data, count)
                    if data == UPDATE_COUNT_TRIGGER:
                        # Use this count to compute the global number
                        # of daily users for this addon.
                        uc.count += count
                elif group == 'app':
                    self.update_app(uc, app_id, app_ver, count)
                elif group == 'os':
                    self.update_os(uc, data, count)
                elif group == 'locale':
                    self.update_locale(uc, data, count)

        # Make sure the locales and versions fields aren't too big to fit in
        # the database. Those two fields are the only ones that are not fully
        # validated, so we could end up with just anything in there (spam,
        # buffer overflow attempts and the like).
        # We don't care that they will increase the numbers, but we do not want
        # those to break the process because of a "Data too long for column
        # 'version'" error.
        # The database field (TEXT), can hold up to 2^16 = 64k characters.
        # If the field is longer than that, we we drop the least used items
        # (with the lower count) until the field fits.
        for addon_guid, update_count in update_counts.iteritems():
            self.trim_field(update_count.locales)
            self.trim_field(update_count.versions)

        # Create in bulk: this is much faster.
        UpdateCount.objects.bulk_create(update_counts.values(), 100)

        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s' % (datetime.now() - start))

        # Clean up files.
        if options['stats_source'] == 'file':
            for _, filepath in group_filepaths:
                log.debug('Deleting {path}'.format(path=filepath))
                unlink(filepath)

    def update_version(self, update_count, version, count):
        """Update the versions on the update_count with the given version."""
        version = version[:32]  # Limit the version to a (random) length.
        update_count.versions = update_inc(
            update_count.versions, version, count
        )

    def update_status(self, update_count, status, count):
        """Update the statuses on the update_count with the given status."""
        # Only update if the given status is valid.
        if status in VALID_STATUSES:
            update_count.statuses = update_inc(
                update_count.statuses, status, count
            )

    def update_app(self, update_count, app_id, app_ver, count):
        """Update the applications on the update_count with the given data."""
        # Only update if app_id is a valid application guid, and if app_ver
        # "could be" a valid version.
        if app_id not in VALID_APP_GUIDS or not re.match(
            APPVERSION_REGEX, app_ver
        ):
            return
        # Applications is a dict of dicts, eg:
        # {"{ec8030f7-c20a-464f-9b0e-13a3a9e97384}":
        #       {"10.0": 2, "21.0": 1, ....},
        #  "some other application guid": ...
        # }
        if update_count.applications is None:
            update_count.applications = {}
        app = update_count.applications.get(app_id, {})
        # Now overwrite this application's dict with
        # incremented counts for its versions.
        update_count.applications.update(
            {app_id: update_inc(app, app_ver, count)}
        )

    def update_os(self, update_count, os, count):
        """Update the OSes on the update_count with the given OS."""
        if os.lower() in amo.PLATFORM_DICT:
            update_count.oses = update_inc(update_count.oses, os, count)

    def update_locale(self, update_count, locale, count):
        """Update the locales on the update_count with the given locale."""
        locale = locale.replace('_', '-')
        # Only update if the locale "could be" valid. We can't simply restrict
        # on locales that AMO know, because Firefox has many more, and custom
        # packaged versions could have even more. Thus, we only restrict on the
        # allowed characters, some kind of format, and the total length, and
        # hope to not miss out on too many locales.
        if re.match(LOCALE_REGEX, locale):
            update_count.locales = update_inc(
                update_count.locales, locale, count
            )

    def trim_field(self, field):
        """Trim (in-place) the dict provided, keeping the most used items.

        The "locales" and "versions" fields are dicts which have the locale
        or version as the key, and the count as the value.

        """

        def fits(field):
            """Does the json version of the field fits in the db TEXT field?"""
            return len(json.dumps(field)) < (2 ** 16)  # Max len of TEXT field.

        if fits(field):
            return
        # Order by count (desc), for a dict like {'<locale>': <count>}.
        values = list(reversed(sorted(field.items(), key=lambda v: v[1])))
        while not fits(field):
            key, count = values.pop()  # Remove the least used (the last).
            del field[key]  # Remove this entry from the dict.
