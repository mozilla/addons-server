import random

from datetime import datetime, timedelta

from olympia.stats.models import DownloadCount


def generate_download_counts(addon, x_days=100):
    """Generate download counts for the last X days."""
    for days in range(x_days):
        date = datetime.now().replace(microsecond=0) - timedelta(days=days)
        source = {
            0: None,
            1: 'search',
            2: 'dp-btn-primary',
            3: None,
            4: 'homepagepromo',
            5: 'discovery-promo',
        }[days % 5]
        DownloadCount.objects.create(
            addon=addon,
            count=random.randrange(0, 1000),
            date=date,
            sources={source: random.randrange(0, 500)} if source else None,
        )
