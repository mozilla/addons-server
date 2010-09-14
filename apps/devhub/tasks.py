import logging
import sys
import time
import traceback

from celeryutils import task

from amo.decorators import write
from files.models import FileUpload

log = logging.getLogger('z.devhub.task')


@task
@write
def validator(upload_id, **kw):
    log.info('VALIDATING: %s' % upload_id)
    upload = FileUpload.objects.get(pk=upload_id)
    try:
        result = _validator(upload)
        upload.update(validation=result)
    except:
        # Store the error with the FileUpload job, then raise
        # it for normal logging.
        tb = traceback.format_exception(*sys.exc_info())
        upload.update(task_error=''.join(tb))
        raise


def _validator(upload):
    time.sleep(3)
    return 'oh nice'
