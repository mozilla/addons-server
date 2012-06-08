import datetime

from django.core.management import call_command

import commonware.log
import cronjobs

from stats.models import Contribution
from mkt.webapps.models import Installed
from . import tasks

cron_log = commonware.log.getLogger('mkt.cron')


@cronjobs.register
def index_latest_mkt_stats():
    latest_contribution = Contribution.search().order_by('-date'
        ).values_dict()[0]['date']
    latest_install = Installed.search().order_by('-date'
        ).values_dict()[0]['date']

    latest = min(latest_contribution, latest_install)

    fmt = lambda d: d.strftime('%Y-%m-%d')
    date_range = '%s:%s' % (fmt(latest), fmt(datetime.date.today()))
    cron_log.info('index_mkt_stats --date=%s' % date_range)
    call_command('index_mkt_stats', addons=None, date=date_range)


@cronjobs.register
def index_mkt_stats():
    cron_log.info('index_mkt_stats')
    call_command('index_mkt_stats', addons=None, date=None)
