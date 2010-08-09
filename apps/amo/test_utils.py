from django.core.cache import cache

from addons import cron
from addons.models import Addon

class ExtraSetup(object):

    def _pre_setup(self):
        super(ExtraSetup, self)._pre_setup()
        cron._update_appsupport(Addon.objects.values_list('id', flat=True))
        cron._update_addons_current_version(Addon.objects.values_list('id'))
        cache.clear()
