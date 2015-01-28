import logging

from celeryutils import task

from versions.models import Version
from lib.crypto.packaged import SigningError

log = logging.getLogger('z.task')


@task
def sign_addons(addon_ids, **kw):
    log.info('[%s] Signing addons.' % len(addon_ids))
    for version in Version.objects.filter(addon_id__in=addon_ids):
        try:
            version.sign_files()
        except SigningError as e:
            log.warning('Failed signing version %s: %s.' % (version.pk, e))
