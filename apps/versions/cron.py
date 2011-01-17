import commonware.log
import cronjobs

from .models import ApplicationsVersions

log = commonware.log.getLogger('z.cron')

@cronjobs.register
def update_compat_info_for_fx4():
    """This is a temporary job to update firefox compatibility from 4.0 to 4.0.*
    on a daily basis.  Once we fix the UI this can go away.  See bug 624305.
    @TODO"""

    log.info("Setting compatilibity from 4.0 to 4.0.*")
    ApplicationsVersions.objects.filter(max=364).update(max=363)
