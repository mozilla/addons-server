import datetime

from django.core.management.base import BaseCommand
from django.db import connection

import olympia.core.logger

from olympia.stats.models import (
    ThemeUpdateCount,
    ThemeUpdateCountBulk,
    ThemeUserCount,
)


log = olympia.core.logger.getLogger('adi.themepopularitymovers')


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
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        # Average number of users over the last 7 days (0 to 6 days ago), in
        # a list of tuples (addon_id, persona_id, count)
        last_week_avgs = ThemeUpdateCount.objects.get_range_days_avg(
            yesterday - datetime.timedelta(days=6),
            yesterday,
            'addon__persona__id',
        )

        # Average number of users over the three weeks before last week
        # (7 to 27 days ago), in dictionary form ({addon_id: count}).
        prev_3_weeks_avgs = dict(
            ThemeUpdateCount.objects.get_range_days_avg(
                yesterday - datetime.timedelta(days=27),
                yesterday - datetime.timedelta(days=7),
            )
        )

        temp_update_counts = []
        theme_user_counts = []

        for addon_id, persona_id, popularity in last_week_avgs:
            if not persona_id or not addon_id:
                continue
            # Create the temporary ThemeUpdateCountBulk for later bulk create.
            prev_3_weeks_avg = prev_3_weeks_avgs.get(addon_id, 0)
            theme_update_count_bulk = ThemeUpdateCountBulk(
                persona_id=persona_id, popularity=popularity, movers=0
            )
            # Set movers to 0 if values aren't high enough.
            if popularity > 100 and prev_3_weeks_avg > 1:
                theme_update_count_bulk.movers = (
                    popularity - prev_3_weeks_avg
                ) / prev_3_weeks_avg

            theme_user_count = ThemeUserCount(
                addon_id=addon_id,
                count=popularity,
                date=today,  # ThemeUserCount date is the processing date.
            )

            temp_update_counts.append(theme_update_count_bulk)
            theme_user_counts.append(theme_user_count)

        # Create in bulk: this is much faster.
        ThemeUpdateCountBulk.objects.all().delete()  # Clean slate first.
        ThemeUpdateCountBulk.objects.bulk_create(temp_update_counts, 100)
        ThemeUserCount.objects.bulk_create(theme_user_counts, 100)

        # Update Personas table in bulk from the above temp table: again, much
        # faster.
        raw_query = """
            UPDATE personas p, theme_update_counts_bulk t
            SET p.popularity=t.popularity,
                p.movers=t.movers
            WHERE t.persona_id=p.id
        """

        with connection.cursor() as cursor:
            cursor.execute(raw_query)

        log.debug(
            'Total processing time: %s' % (datetime.datetime.now() - start)
        )
