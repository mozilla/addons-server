import json
import urlparse

from django.conf import settings
from django.db import models

import commonware.log

import amo
import amo.models
from amo.urlresolvers import reverse
from addons import query
from addons.models import (Addon, update_name_table, update_search_index,
                           delete_search_index)


log = commonware.log.getLogger('z.addons')


class WebappManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(WebappManager, self).get_query_set()
        qs = qs._clone(klass=query.IndexQuerySet)
        return qs.filter(type=amo.ADDON_WEBAPP)

    def reviewed(self):
        return self.filter(status__in=amo.REVIEWED_STATUSES)

    def listed(self):
        return self.reviewed().filter(_current_version__isnull=False,
                                      disabled_by_user=False)


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

    def get_url_path(self, more=False):
        view = 'apps.detail_more' if more else 'apps.detail'
        return reverse(view, args=[self.app_slug])

    @staticmethod
    def domain_from_url(url):
        if not url:
            raise ValueError('URL was empty')
        hostname = urlparse.urlparse(url).hostname
        if hostname:
            hostname = hostname.lower()
            if hostname.startswith('www.'):
                hostname = hostname[4:]
        return hostname

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
    def origin(self):
        parsed = urlparse.urlparse(self.manifest_url)
        return '%s://%s' % (parsed.scheme, parsed.netloc)

    def get_manifest_json(self):
        cur = self.current_version
        try:
            # The first file created for each version of the web app
            # is the manifest.
            manifest = cur.files.order_by('created')[0]
            with open(manifest.file_path, 'r') as mf:
                return json.load(mf)
        except Exception, e:
            log.error('Failed to open the manifest for webapp %s,'
                      ' version %s: %s.' % (self.pk, cur, e.message))
            raise

    def share_url(self):
        return reverse('apps.share', args=[self.app_slug])


# Pull all translated_fields from Addon over to Webapp.
Webapp._meta.translated_fields = Addon._meta.translated_fields


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='webapps.index')
models.signals.post_save.connect(update_name_table, sender=Webapp,
                                 dispatch_uid='webapps.update.name.table')
models.signals.post_delete.connect(delete_search_index, sender=Webapp,
                                   dispatch_uid='webapps.unindex')


class Installed(amo.models.ModelBase):
    """Track WebApp installations."""
    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user')
