from celeryutils import task
import commonware.log


task_log = commonware.log.getLogger('z.task')


@task
def extract_file(viewer, **kw):
    task_log.info('[1@%s] Unzipping %s for file viewer.' % (
                  extract_file.rate_limit, viewer))
    try:
        viewer.extract()
    except ValueError, msg:
        task_log.error('[1@%s] Error unzipping: %s' %
                       (extract_file.rate_limit, msg))
