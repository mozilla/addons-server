import json
import logging
import os
import sys
import traceback

from django.core import management

from celeryutils import task

from amo.decorators import write
from amo.utils import resize_image
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

    # TODO(Kumar) remove this once we sort
    # out the js environment. See bug 614574
    from validator.testcases import scripting
    scripting.SPIDERMONKEY = None

    # TODO(basta): this should be two lines.
    # from addon_validator import validate
    # return validate(path, format='json')
    from cStringIO import StringIO
    import validator.main as addon_validator
    from validator.errorbundler import ErrorBundle
    from validator.constants import PACKAGE_ANY
    output = StringIO()

    # determined=True
    #   continue validating each tier even if one has an error
    # listed=True
    #   the add-on is hosted on AMO
    eb = ErrorBundle(pipe=output, no_color=True,
                     determined=True, listed=True)
    addon_validator.prepare_package(eb, upload.path, PACKAGE_ANY)
    eb.print_json()
    return output.getvalue()


@task(queue='images')
def resize_icon(src, dst, size, **kw):
    """Resizes addon icons."""
    log.info('[1@None] Resizing icon: %s' % dst)

    try:
        if isinstance(size, list):
            for s in size:
                resize_image(src, '%s-%s.png' % (dst, s), (s, s),
                             remove_src=False)
            os.remove(src)
        else:
            resize_image(src, dst, (size, size), remove_src=True)

    except Exception, e:
        log.error("Error saving addon icon: %s" % e)
