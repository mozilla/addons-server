import logging

from celeryutils import task

from webapps.models import Webapp

task_log = logging.getLogger('z.task')


@task(rate_limit='15/m')
def webapp_update_weekly_downloads(data, **kw):
    task_log.info("[%s@%s] Update weekly downloads." %
                   (len(data), webapp_update_weekly_downloads.rate_limit))

    for line in data:
        webapp = Webapp.objects.get(pk=line['addon'])
        webapp.update(weekly_downloads=line['count'])
