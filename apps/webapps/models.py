from django.db import models

import amo
from amo.urlresolvers import reverse
from addons.models import Addon, update_search_index, delete_search_index


# We use super(Addon, self) on purpose to override expectations in Addon that
# are not true for Webapp. Webapp is just inheriting so it can share the db
# table.
class Webapp(Addon):

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


# These are the translated strings we want to pull in.
translated = 'name', 'summary', 'description'
Webapp._meta.translated_fields = [f for f in Webapp._meta.fields
                                  if f.name in translated]


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='webapps.index')
models.signals.post_delete.connect(delete_search_index, sender=Webapp,
                                   dispatch_uid='webapps.unindex')
