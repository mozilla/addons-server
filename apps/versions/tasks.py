from celeryutils import task
import commonware.log

from django.db.models.signals import post_save

from versions.models import Version, update_status
from apps.addons.models import version_changed
from apps.addons.signals import version_changed as version_changed_signal


task_log = commonware.log.getLogger('z.task')


# TODO(andym): remove this when versions all done.
@task(rate_limit='10/m')
def add_version_int(pks, **kw):
    task_log.info("[%d@%s] Adding version_int for versions staring at id=%d" %
                  (len(pks), add_version_int.rate_limit, pks[0]))

    version_changed_signal.disconnect(version_changed,
                                      dispatch_uid='version_changed')
    post_save.disconnect(update_status, sender=Version,
                         dispatch_uid='version_update_status')

    versions = Version.objects.filter(pk__in=pks)
    for version in versions:
        version.save()
