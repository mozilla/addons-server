from datetime import datetime

from django.core.management.base import BaseCommand

import commonware.log

from addons.models import Persona
from stats.models import ThemeUpdateCount


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
        one_week_avg = ThemeUpdateCount.objects.get_last_x_days_avg(7)

        # Average number of users over the last three weeks (21 days).
        three_weeks_avg = ThemeUpdateCount.objects.get_last_x_days_avg(21)

        # Transform the querysets from a list of dicts
        #   [{'addon_id': id1, 'count__avg': avg1], {'addon_id': id2, ...
        # to a dict
        #   {id1: avg1, id2: avg2, ...}
        one_week_avg_dict = {}
        for d in one_week_avg:
            one_week_avg_dict[d['addon_id']] = d['count__avg']
        three_weeks_avg_dict = {}
        for d in three_weeks_avg:
            three_weeks_avg_dict[d['addon_id']] = d['count__avg']

        # Loop over the three_weeks_avg_dict, which can't be shorter than the
        # one_week_avg_dict.
        for addon_id, three_weeks_avg in three_weeks_avg_dict.iteritems():
            popularity = int(one_week_avg_dict.get(addon_id, 0))
            Persona.objects.filter(addon_id=addon_id).update(
                # TODO: remove _tmp from the fields when the ADI stuff is used
                popularity_tmp=popularity,
                movers_tmp=(popularity - three_weeks_avg) / three_weeks_avg)

        log.debug('Total processing time: %s' % (datetime.now() - start))
