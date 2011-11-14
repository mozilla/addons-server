# -*- coding: utf-8 -*-
import json
import time
import urlparse

from django.conf import settings
from django.db import models

import commonware.log

import amo
from amo.decorators import skip_cache
from amo.helpers import absolutify
import amo.models
from amo.urlresolvers import reverse
from amo.utils import memoize
from addons import query
from addons.models import (Addon, clear_name_table, delete_search_index,
                           update_name_table, update_search_index)

import jwt


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

    @skip_cache
    def pending(self):
        # - Holding
        # ** Approved   -- PUBLIC
        # ** Unapproved -- PENDING
        # - Open
        # ** Reviewed   -- PUBLIC
        # ** Unreviewed -- LITE
        # ** Rejected   -- REJECTED
        status = (amo.STATUS_PENDING if settings.WEBAPPS_RESTRICTED
                  else amo.STATUS_PUBLIC)
        return self.filter(status=status)


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

    def get_receipt(self, user):
        """Gets the receipt for the user for this webapp, or None."""
        try:
            return self.installed.get(user=user).receipt
        except Installed.DoesNotExist:
            return


# Pull all translated_fields from Addon over to Webapp.
Webapp._meta.translated_fields = Addon._meta.translated_fields


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='webapps.index')
models.signals.post_save.connect(update_name_table, sender=Webapp,
                                 dispatch_uid='webapps.update.name.table')
models.signals.post_delete.connect(delete_search_index, sender=Webapp,
                                   dispatch_uid='webapps.unindex')
models.signals.pre_delete.connect(clear_name_table, sender=Webapp,
                                  dispatch_uid='webapps.clear.name.table')


class Installed(amo.models.ModelBase):
    """Track WebApp installations."""
    addon = models.ForeignKey('addons.Addon', related_name='installed')
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user')

    @property
    def receipt(self):
        if self.addon.is_webapp():
            return create_receipt(self.pk)
        return ''


@memoize(prefix='create-receipt', time=60 * 10)
def create_receipt(installed_pk):
    installed = Installed.objects.get(pk=installed_pk)
    verify = reverse('api.market.verify', args=[installed.addon.pk])
    detail = reverse('users.purchases.receipt', args=[installed.addon.pk])
    receipt = dict(typ='purchase-receipt',
                   product=installed.addon.origin,
                   user={'type': 'email',
                         'value': installed.user.email},
                   iss=settings.SITE_URL,
                   nbf=time.mktime(installed.created.timetuple()),
                   iat=time.time(),
                   detail=absolutify(detail),
                   verify=absolutify(verify))
    return jwt.encode(receipt, get_key(), u'RS512')


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)


def decode_receipt(receipt):
    """
    Cracks the receipt using the private key. This will probably change
    to using the cert at some point, especially when we get the HSM.
    """
    return jwt.decode(receipt, get_key())
