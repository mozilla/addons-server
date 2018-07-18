import datetime

from mkt.monolith.models import MonolithRecord
from stats.models import GlobalStat


METRIC = 'apps_count_installed'


def run():
    """Backfill apps_count_installed."""
    # Get the first metric and increment daily until today's date.
    today = datetime.datetime.today().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    try:
        date = (
            MonolithRecord.objects.order_by('recorded').values('recorded')[0][
                'recorded'
            ]
        ).replace(hour=0, minute=0, second=0, microsecond=0)
    except IndexError:
        return  # No monolith data. Bail out.

    while date < today:
        next_date = date + datetime.timedelta(days=1)

        # Delete the old stats for this date.
        GlobalStat.objects.filter(name=METRIC, date=date.date()).delete()

        # Add it back with the count from the Monolith table.
        count = MonolithRecord.objects.filter(
            recorded__range=(date, next_date), key='install'
        ).count()
        GlobalStat.objects.create(name=METRIC, date=date.date(), count=count)

        date = next_date
