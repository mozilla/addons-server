import datetime

from django.core.management import call_command

import waffle

import olympia.core.logger
from olympia.lib.es.utils import raise_if_reindex_in_progress

from .models import DownloadCount


log = olympia.core.logger.getLogger('z.cron')


def index_latest_stats(index=None):
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    def fmt(d):
        return d.strftime('%Y-%m-%d')

    raise_if_reindex_in_progress('amo')
    latest = DownloadCount.search(index).order_by('-date').values_dict('date')
    if latest:
        latest = latest[0]['date']
    else:
        latest = fmt(datetime.date.today() - datetime.timedelta(days=1))
    date_range = '%s:%s' % (latest, fmt(datetime.date.today()))
    log.info('index_stats --date=%s' % date_range)
    call_command('index_stats', addons=None, date=date_range)
