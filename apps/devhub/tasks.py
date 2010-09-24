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
    # TODO(basta): this should be two lines.
    # from addon_validator import validate
    # return validate(path, format='json')
    from cStringIO import StringIO
    import validator.main as addon_validator
    from validator.errorbundler import ErrorBundle
    from validator.constants import PACKAGE_ANY
    output = StringIO()
    # I have no idea what these params mean.
    eb = ErrorBundle(output, True)
    eb.determined = True
    eb.save_resource('listed', True)
    addon_validator.prepare_package(eb, upload.path, PACKAGE_ANY)
    eb.print_json()
    return output.getvalue()
