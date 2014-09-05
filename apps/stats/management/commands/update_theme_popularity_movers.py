from datetime import datetime

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
        start = datetime.now()  # Measure the time it takes to run the script.

        # Average number of users over the last 7 days.
        one_week_averages = ThemeUpdateCount.objects.get_last_x_days_avg(7)

        # Average number of users over the last three weeks (21 days).
        three_weeks_averages = ThemeUpdateCount.objects.get_last_x_days_avg(21)

        # Perf: memoize the addon to persona relation.
        addon_to_persona = dict(Persona.objects.values_list('addon_id', 'id'))

        temp_update_counts = []

        # Loop over the three_weeks_avg_dict, which can't be shorter than the
        # one_week_avg_dict.
        for addon_id, three_weeks_avg in three_weeks_averages.iteritems():
            # Create the temporary ThemeUpdateCountBulk for later bulk create.
            pop = one_week_averages.get(addon_id, 0)
            tucb = ThemeUpdateCountBulk(
                persona_id=addon_to_persona[addon_id],
                popularity=pop,
                movers=(pop - three_weeks_avg) / three_weeks_avg)
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

        log.debug('Total processing time: %s' % (datetime.now() - start))
