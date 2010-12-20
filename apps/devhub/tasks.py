import json
import logging
import os
import sys
import traceback

from django.conf import settings
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
        upload.validation = result
        upload.save()  # We want to hit the custom save().
    except:
        # Store the error with the FileUpload job, then raise
        # it for normal logging.
        tb = traceback.format_exception(*sys.exc_info())
        upload.update(task_error=''.join(tb))
        raise


def _validator(upload):

    import validator
    from validate import validate

    # TODO(Kumar) remove this when validator is fixed, see bug 620503
    from validator.testcases import scripting
    scripting.SPIDERMONKEY_INSTALLATION = settings.SPIDERMONKEY
    import validator.constants
    validator.constants.SPIDERMONKEY_INSTALLATION = settings.SPIDERMONKEY

    # TODO(Kumar) remove this when validator is fixed, see bug 620503
    # TODO(Kumar) Or better yet, keep apps up to date with DB per bug 620731
    apps = os.path.join(os.path.dirname(validator.__file__),
                        'app_versions.json')

    return validate(upload.path, format='json',
                    # Continue validating each tier even if one has an error
                    determined=True,
                    approved_applications=apps,
                    spidermonkey=settings.SPIDERMONKEY)


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
