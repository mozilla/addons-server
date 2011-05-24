from django.conf import settings

from celeryutils import task
import commonware.log
from tower import ugettext as _

from amo.utils import Message
from .models import File

task_log = commonware.log.getLogger('z.task')


@task
def extract_file(viewer, **kw):
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    task_log.info('[1@%s] Unzipping %s for file viewer.' % (
                  extract_file.rate_limit, viewer))

    try:
        viewer.extract()
    except Exception, err:
        if settings.DEBUG:
            msg.save(_('There was an error accessing file %s. %s.') %
                     (viewer, err))
        else:
            msg.save(_('There was an error accessing file %s.') % viewer)
        task_log.error('[1@%s] Error unzipping: %s' %
                       (extract_file.rate_limit, err))


@task
def repackage_jetpack(builder_data, **kw):
    task_log.info('[1@None] Repackaging jetpack for %s.' % builder_data['id'])
