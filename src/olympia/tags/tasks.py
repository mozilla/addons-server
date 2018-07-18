import olympia.core.logger

from olympia.amo.celery import task
from olympia.tags.models import Tag


task_log = olympia.core.logger.getLogger('z.task')


@task(rate_limit='10/m')
def update_all_tag_stats(pks, **kw):
    task_log.info(
        "[%s@%s] Calculating stats for tags starting with %s"
        % (len(pks), update_all_tag_stats.rate_limit, pks[0])
    )
    for tag in Tag.objects.filter(pk__in=pks):
        tag.update_stat()


@task(rate_limit='1000/m')
def update_tag_stat(tag_pk, **kw):
    tag = Tag.objects.get(pk=tag_pk)
    task_log.info(
        "[1@%s] Calculating stats for tag %s"
        % (update_tag_stat.rate_limit, tag.pk)
    )
    tag.update_stat()
