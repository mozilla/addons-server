import random

from datetime import datetime, timedelta

from olympia.amo import FIREFOX
from olympia.stats.models import DownloadCount, UpdateCount


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


def generate_update_counts(addon, x_days=100):
    """Generate update counts for the last X days."""
    for days in range(x_days):
        date = datetime.now().replace(microsecond=0) - timedelta(days=days)
        versions = {}
        applications = {
            FIREFOX.guid: {
                '70.0.0': random.randrange(0, 10),
                '71.0.0': random.randrange(0, 10),
                '72.0.0': random.randrange(0, 10),
                '73.0.0': random.randrange(0, 10),
                '74.0.0': random.randrange(0, 10),
                '75.0.0': random.randrange(0, 10),
                '76.0.0': random.randrange(0, 10),
            }
        }
        oses = {
            'Darwin': random.randrange(0, 10),
            'Linux': random.randrange(0, 10),
            'WINNT': random.randrange(0, 10),
        }
        locales = {
            'de-DE': random.randrange(0, 10),
            'en-US': random.randrange(0, 10),
            'fr-FR': random.randrange(0, 10),
        }
        UpdateCount.objects.create(
            addon=addon,
            count=random.randrange(0, 100),
            date=date,
            versions=versions,
            applications=applications,
            oses=oses,
            locales=locales,
        )
