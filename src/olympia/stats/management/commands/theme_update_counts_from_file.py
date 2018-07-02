from datetime import datetime, timedelta
from os import path, unlink

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, MigratedLWT, Persona
from olympia.stats.models import ThemeUpdateCount, UpdateCount

from . import get_date, get_stats_data


log = olympia.core.logger.getLogger('adi.themeupdatecount')


class Command(BaseCommand):
    """Process hive results stored in different files and store them in the db.

    Usage:
    ./manage.py theme_update_counts_from_file \
        <folder> --date=YYYY-MM-DD --stats_source={s3,file}

    If no date is specified, the default is the day before.

    If no stats_source is specified, the default is set to s3.

    If stats_source is file:
        If not folder is specified, the default is `hive_results/YYYY-MM-DD/`.
        This folder will be located in `<settings.NETAPP_STORAGE>/tmp`.

        File processed:
        - theme_update_counts.hive

    If stats_source is s3:
        This file will be located in
            `<settings.AWS_STATS_S3_BUCKET>/amo_stats`.

        File processed:
        - theme_update_counts/YYYY-MM-DD/000000_0

    Each file has the following cols:
    - date
    - addon id (if src is not "gp") or persona id
    - src (if it's "gp" then it's an old request with the persona id)
    - count

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
        sep = options['separator']
        start = datetime.now()  # Measure the time it takes to run the script.
        day = options['date']
        if not day:
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        if options['stats_source'] == 's3':
            filepath = 's3://' + '/'.join([settings.AWS_STATS_S3_BUCKET,
                                           'amo_stats', 'theme_update_counts',
                                           day, '000000_0'])

        elif options['stats_source'] == 'file':
            folder = options['folder_name']
            folder = path.join(settings.TMP_PATH, folder, day)
            filepath = path.join(folder, 'theme_update_counts.hive')

        # Make sure we're not trying to update with mismatched data.
        if get_date(filepath, sep) != day:
            raise CommandError('%s file contains data for another day' %
                               filepath)

        # First, make sure we don't have any existing counts for the same day,
        # or it would just increment again the same data.
        ThemeUpdateCount.objects.filter(date=day).delete()

        theme_update_counts = {}
        new_stheme_update_counts = {}

        # Preload a set containing the ids of all the persona Add-on objects
        # that we care about. When looping, if we find an id that is not in
        # that set, we'll reject it.
        addons = set(Addon.objects.filter(type=amo.ADDON_PERSONA,
                                          status=amo.STATUS_PUBLIC,
                                          persona__isnull=False)
                                  .values_list('id', flat=True))
        # Preload a dict of persona to static theme ids that are migrated.
        migrated_personas = dict(
            MigratedLWT.objects.values_list(
                'lightweight_theme_id', 'static_theme_id')
        )
        existing_stheme_update_counts = {
            uc.addon_id: uc for uc in UpdateCount.objects.filter(
                addon_id__in=migrated_personas.values())}
        # Preload all the Personas once and for all. This builds a dict where
        # each key (the persona_id we get from the hive query) has the addon_id
        # as value.
        persona_to_addon = dict(Persona.objects.values_list('persona_id',
                                                            'addon_id'))

        count_file = get_stats_data(filepath)
        for index, line in enumerate(count_file):
            if index and (index % 1000000) == 0:
                log.info('Processed %s lines' % index)

            splitted = line[:-1].split(sep)

            if len(splitted) != 4:
                log.debug('Badly formatted row: %s' % line)
                continue

            day, id_, src, count = splitted
            try:
                id_, count = int(id_), int(count)
            except ValueError:  # Badly formatted? Drop.
                continue

            if src:
                src = src.strip()

            # If src is 'gp', it's an old request for the persona id.
            if id_ not in persona_to_addon and src == 'gp':
                continue  # No such persona.
            addon_id = persona_to_addon[id_] if src == 'gp' else id_

            # Is the persona already migrated to static theme?
            if addon_id in migrated_personas:
                mig_addon_id = migrated_personas[addon_id]
                if mig_addon_id in existing_stheme_update_counts:
                    existing_stheme_update_counts[mig_addon_id].count += count
                    existing_stheme_update_counts[mig_addon_id].save()
                elif mig_addon_id in new_stheme_update_counts:
                    new_stheme_update_counts[mig_addon_id].count += count
                else:
                    new_stheme_update_counts[mig_addon_id] = UpdateCount(
                        addon_id=mig_addon_id, date=day, count=count)

            # Does this addon exist?
            if addon_id not in addons:
                continue

            # Memoize the ThemeUpdateCount.
            if addon_id in theme_update_counts:
                tuc = theme_update_counts[addon_id]
            else:
                tuc = ThemeUpdateCount(addon_id=addon_id, date=day,
                                       count=0)
                theme_update_counts[addon_id] = tuc

            # We can now fill the ThemeUpdateCount object.
            tuc.count += count

        # Create in bulk: this is much faster.
        ThemeUpdateCount.objects.bulk_create(theme_update_counts.values(), 100)
        UpdateCount.objects.bulk_create(new_stheme_update_counts.values(), 100)

        log.info('Processed a total of %s lines' % (index + 1))
        log.debug('Total processing time: %s' % (datetime.now() - start))

        # Clean up file.
        if options['stats_source'] == 'file':
            log.debug('Deleting {path}'.format(path=filepath))
            unlink(filepath)
