import urlparse

from django.conf import settings
from django.db import models

import amo
import amo.models
from amo.urlresolvers import reverse
from addons.models import Addon, update_search_index, delete_search_index


class WebappManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(WebappManager, self).get_query_set()
        return qs.filter(type=amo.ADDON_WEBAPP)


# We use super(Addon, self) on purpose to override expectations in Addon that
# are not true for Webapp. Webapp is just inheriting so it can share the db
# table.
class Webapp(Addon):

    objects = WebappManager()

    class Meta:
        proxy = True

    def save(self, **kw):
        # Make sure we have the right type.
        self.type = amo.ADDON_WEBAPP
        self.clean_slug(slug_field='app_slug')
        creating = not self.id
        super(Addon, self).save(**kw)
        if creating:
            # Set the slug once we have an id to keep things in order.
            self.update(slug='app-%s' % self.id)

    def get_url_path(self, impala=None, more=False):
        view = 'apps.detail_more' if more else 'apps.detail'
        return reverse(view, args=[self.app_slug])

    @classmethod
    def pending(cls):
        # - Holding
        # ** Approved   -- PUBLIC
        # ** Unapproved -- PENDING
        # - Open
        # ** Reviewed   -- PUBLIC
        # ** Unreviewed -- LITE
        # ** Rejected   -- REJECTED
        status = (amo.STATUS_PENDING if settings.WEBAPPS_RESTRICTED
                  else amo.STATUS_LITE)
        return cls.uncached.filter(status=status)

    @property
    def get_origin(self):
        parsed = urlparse.urlparse(self.manifest_url)
        return '%s://%s' % (parsed.scheme, parsed.netloc)


# These are the translated strings we want to pull in.
translated = 'name', 'summary', 'description'
Webapp._meta.translated_fields = [f for f in Webapp._meta.fields
                                  if f.name in translated]


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='webapps.index')
models.signals.post_delete.connect(delete_search_index, sender=Webapp,
                                   dispatch_uid='webapps.unindex')
