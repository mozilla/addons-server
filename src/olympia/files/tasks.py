import logging

from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.files.models import File, WebextPermission
from olympia.files.utils import parse_xpi


log = logging.getLogger('z.files.task')


@task
@write
def extract_webext_permissions(ids, **kw):
    log.info('[%s@%s] Extracting permissions from Files, starting at id: %s...'
             % (len(ids), extract_webext_permissions.rate_limit, ids[0]))
    files = File.objects.filter(pk__in=ids).no_transforms()

    for file_ in files:
        try:
            log.info('Parsing File.id: %s @ %s' %
                     (file_.pk, file_.current_file_path))
            parsed_data = parse_xpi(file_.current_file_path, check=False)
            permissions = parsed_data.get('permissions')
            if permissions:
                log.info('Found %s permissions for: %s' %
                         (len(permissions), file_.pk))
                WebextPermission.objects.update_or_create(
                    defaults={'permissions': permissions}, file=file_)
        except Exception, err:
            log.error('Failed to extract: %s, error: %s' % (file_.pk, err))
