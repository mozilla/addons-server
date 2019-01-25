from django.conf import settings

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.files.models import File, WebextPermission
from olympia.files.utils import parse_xpi
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.files.task')


@task
@use_primary_db
def extract_webext_permissions(ids, **kw):
    log.info('[%s@%s] Extracting permissions from Files, starting at id: %s...'
             % (len(ids), extract_webext_permissions.rate_limit, ids[0]))
    files = File.objects.filter(pk__in=ids).no_transforms()

    # A user needs to be passed down to parse_xpi(), so we use the task user.
    user = UserProfile.objects.get(pk=settings.TASK_USER_ID)

    for file_ in files:
        try:
            log.info('Parsing File.id: %s @ %s' %
                     (file_.pk, file_.current_file_path))
            parsed_data = parse_xpi(file_.current_file_path, user=user)
            permissions = parsed_data.get('permissions', [])
            # Add content_scripts host matches too.
            for script in parsed_data.get('content_scripts', []):
                permissions.extend(script.get('matches', []))
            if permissions:
                log.info('Found %s permissions for: %s' %
                         (len(permissions), file_.pk))
                WebextPermission.objects.update_or_create(
                    defaults={'permissions': permissions}, file=file_)
        except Exception as err:
            log.error('Failed to extract: %s, error: %s' % (file_.pk, err))
