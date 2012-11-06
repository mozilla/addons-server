import datetime

from django.core.management import call_command

import commonware.log
import cronjobs
import pyes

from stats.models import Contribution
from lib.es.utils import raise_if_reindex_in_progress
from mkt.webapps.models import Installed
from . import tasks

cron_log = commonware.log.getLogger('mkt.cron')


@cronjobs.register
def index_latest_mkt_stats(index=None, aliased=True):
    raise_if_reindex_in_progress()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)

    try:
        latest = Contribution.search(index).order_by('-date').values_dict()
        latest_contribution = latest and latest[0]['date'] or yesterday
    except pyes.exceptions.SearchPhaseExecutionException:
        latest_contribution = yesterday

    try:
        latest = Installed.search(index).order_by('-date').values_dict()
        latest_install = latest and latest[0]['date'] or yesterday
    except pyes.exceptions.SearchPhaseExecutionException:
        latest_install = yesterday

    latest = min(latest_contribution, latest_install)

    fmt = lambda d: d.strftime('%Y-%m-%d')
    date_range = '%s:%s' % (fmt(latest), fmt(datetime.date.today()))
    cron_log.info('index_mkt_stats --date=%s' % date_range)
    call_command('index_mkt_stats', addons=None, date=date_range, index=index,
                 aliased=True)


@cronjobs.register
def index_mkt_stats(index=None, aliased=True):
    cron_log.info('index_mkt_stats')
    call_command('index_mkt_stats', addons=None, date=None)
