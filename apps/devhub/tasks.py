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
    # Monkeypatch the validator's hard-coded applications & versions.
    from validator.testcases import targetapplication as testcase
    cmd = management.load_command_class('applications', 'dump_apps')
    if not os.path.exists(cmd.JSON_PATH):
        cmd.handle()
    apps = json.load(open(cmd.JSON_PATH))

    testcase.APPLICATIONS = dict((d['guid'], d['name']) for d in apps.values())
    versions = dict((d['guid'], d['versions']) for d in apps.values())
    testcase.APPROVED_APPLICATIONS = versions

    # TODO(Kumar) remove this when it lands in amo-validator (bug 614574)
    import validator.constants
    validator.constants.SPIDERMONKEY_INSTALLATION = 'js'

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


@task
@write
def resize_icon(src, dst, size, **kw):
    """Resizes addon icons."""
    log.info('[1@None] Resizing icon: %s' % dst)

    try:
        resize_image(src, dst, (size, size), False)
    except Exception, e:
        log.error("Error saving addon icon: %s" % e)
