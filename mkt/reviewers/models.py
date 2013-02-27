import json

from django.conf import settings
from django.core.cache import cache
from django.db import models

import amo
from amo.utils import JSONEncoder
from apps.addons.models import Addon
from apps.editors.models import CannedResponse, EscalationQueue, RereviewQueue
from users.models import UserForeignKey

from mkt.site.helpers import product_as_dict
from mkt.webapps.models import Webapp


class AppCannedResponseManager(amo.models.ManagerBase):
    def get_query_set(self):
        qs = super(AppCannedResponseManager, self).get_query_set()
        return qs.filter(type=amo.CANNED_RESPONSE_APP)


class AppCannedResponse(CannedResponse):
    objects = AppCannedResponseManager()

    class Meta:
        proxy = True


class ThemeLock(amo.models.ModelBase):
    theme = models.OneToOneField('addons.Persona')
    reviewer = UserForeignKey()
    expiry = models.DateTimeField()

    class Meta:
        db_table = 'theme_locks'


def cleanup_queues(sender, instance, **kwargs):
    RereviewQueue.objects.filter(addon=instance).delete()
    EscalationQueue.objects.filter(addon=instance).delete()


# Don't add this signal in if we are not in the marketplace.
if settings.MARKETPLACE:
    models.signals.post_delete.connect(cleanup_queues, sender=Addon,
                                       dispatch_uid='queue-addon-cleanup')


class AppsReviewing(object):
    """
    Class to manage the list of apps a reviewer is currently reviewing.

    Data is stored in memcache.
    """

    def __init__(self, request):
        self.request = request
        self.user_id = request.amo_user.id
        self.key = '%s:myapps:%s' % (settings.CACHE_PREFIX, self.user_id)

    def get_apps(self):
        ids = []
        my_apps = cache.get(self.key)
        if my_apps:
            for id in my_apps.split(','):
                valid = cache.get(
                    '%s:review_viewing:%s' % (settings.CACHE_PREFIX, id))
                if valid and valid == self.user_id:
                    ids.append(id)

        apps = []
        for app in Webapp.objects.filter(id__in=ids):
            apps.append({
                'app': app,
                'app_attrs': json.dumps(
                    product_as_dict(self.request, app, False, 'reviewer'),
                    cls=JSONEncoder),
            })
        return apps

    def add(self, addon_id):
        my_apps = cache.get(self.key)
        if my_apps:
            apps = my_apps.split(',')
        else:
            apps = []
        apps.append(addon_id)
        cache.set(self.key, ','.join(map(str, set(apps))),
                  amo.EDITOR_VIEWING_INTERVAL * 2)
