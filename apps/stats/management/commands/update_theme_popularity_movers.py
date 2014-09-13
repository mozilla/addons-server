import datetime

from django.core.management.base import BaseCommand
from django.db import connection

import commonware.log

from addons.models import Persona
from stats.models import ThemeUpdateCount, ThemeUpdateCountBulk


log = commonware.log.getLogger('adi.themepopularitymovers')


class Command(BaseCommand):
    """Compute the popularity and movers of themes from ADI data.

    Usage:
    ./manage.py update_theme_popularity_movers

    This will compute the popularity and movers of each theme, and store them
    in the Persona associated.

    Popularity: average number of users over the last 7 days.
    Movers: (popularity - (last 21 days avg)) / (last 21 days avg)

    """
    help = __doc__

    def handle(self, *args, **options):
        start = datetime.datetime.now()  # Measure the time it takes to run.
        # The theme_update_counts_from_* gather data for the day before, at
        # best.
        yesterday = datetime.date.today() - datetime.timedelta(days=1)

        # Average number of users over the last 7 days (0 to 6 days ago).
        last_week_avgs = ThemeUpdateCount.objects.get_range_days_avg(
            start=yesterday - datetime.timedelta(days=6), end=yesterday)

        # Average number of users over the three weeks before last week
        # (7 to 27 days ago).
        prev_3_weeks_avgs = ThemeUpdateCount.objects.get_range_days_avg(
            start=yesterday - datetime.timedelta(days=27),
            end=yesterday - datetime.timedelta(days=7))

        # Perf: memoize the addon to persona relation.
        addon_to_persona = dict(Persona.objects.values_list('addon_id', 'id'))

        temp_update_counts = []

        for addon_id, popularity in last_week_avgs.iteritems():
            if addon_id not in addon_to_persona:
                continue
            # Create the temporary ThemeUpdateCountBulk for later bulk create.
            prev_3_weeks_avg = prev_3_weeks_avgs.get(addon_id, 0)
            tucb = ThemeUpdateCountBulk(
                persona_id=addon_to_persona[addon_id],
                popularity=popularity,
                movers=0)
            # Set movers to 0 if values aren't high enough.
            if popularity > 100 and prev_3_weeks_avg > 1:
                tucb.movers = (
                    popularity - prev_3_weeks_avg) / prev_3_weeks_avg
            temp_update_counts.append(tucb)

        # Create in bulk: this is much faster.
        ThemeUpdateCountBulk.objects.all().delete()  # Clean slate first.
        ThemeUpdateCountBulk.objects.bulk_create(temp_update_counts, 100)

        # Update in bulk from the above temp table: again, much faster.
        # TODO: remove _tmp from the fields when the ADI stuff is used
        raw_query = """
            UPDATE personas p, theme_update_counts_bulk t
            SET p.popularity_tmp=t.popularity,
                p.movers_tmp=t.movers
            WHERE t.persona_id=p.id
        """
        cursor = connection.cursor()
        cursor.execute(raw_query)

        log.debug('Total processing time: %s' % (
            datetime.datetime.now() - start))
