import datetime
import random

from olympia.stats.models import DownloadCount, UpdateCount
from olympia.stats.tasks import index_download_counts


def generate_addon_stats(addon, days_back):
    today = datetime.datetime.today()
    versions = addon.versions.values_list('version', flat=True)

    download_ids = []
    update_ids = []
    for day in range(0, days_back):
        date = (today - datetime.timedelta(days=day)).date()
        download = DownloadCount(
            addon=addon,
            count=random.randint(50, 100),
            date=date,
            sources='populate-stats-day-{}'.format(day)
        )
        # TODO: add in versions, statuses, applications and oses?
        update = UpdateCount(
            addon=addon,
            count=random.randint(50, 100),
            date=date,
            locales=random.choice(['en-US', 'fr', 'de'])
        )
        download_ids.append(download.id)
        update_ids.append(update.id)

    index_download_counts(download_ids)

def test():
    from olympia.addons.models import Addon
    addon = Addon.objects.get(slug='tibia-online-status')
    generate_addon_stats(addon, 10)