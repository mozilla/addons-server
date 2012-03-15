# -*- coding: utf-8 -*-
import json
import time
from urllib import urlencode
import urlparse

from django.conf import settings
from django.core.urlresolvers import NoReverseMatch
from django.db import models
from django.dispatch import receiver

import commonware.log

import amo
from amo.decorators import skip_cache
from amo.helpers import absolutify
import amo.models
from amo.urlresolvers import reverse
from amo.utils import memoize
from addons import query
from addons.models import (Addon, update_name_table, update_search_index)
from files.models import FileUpload, Platform
from versions.models import Version

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

    def top_free(self, listed=True):
        qs = self.listed() if listed else self
        return (qs.filter(premium_type__in=amo.ADDON_FREES)
                .exclude(addonpremium__price__price__isnull=False)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def top_paid(self, listed=True):
        qs = self.listed() if listed else self
        return (qs.filter(premium_type__in=amo.ADDON_PREMIUMS,
                          addonpremium__price__price__gt=0)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    @skip_cache
    def pending(self):
        # - Holding
        # ** Approved   -- PUBLIC
        # ** Unapproved -- PENDING
        # - Open
        # ** Reviewed   -- PUBLIC
        # ** Unreviewed -- LITE
        # ** Rejected   -- REJECTED
        return self.filter(status=amo.WEBAPPS_UNREVIEWED_STATUS)


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

    def get_url_path(self, more=False, add_prefix=True):
        # We won't have to do this when Marketplace absorbs all apps views,
        # but for now pretend you didn't see this.
        try:
            return reverse('detail', args=[self.app_slug],
                           add_prefix=add_prefix)
        except NoReverseMatch:
            # Fall back to old details page until the views get ported.
            return super(Webapp, self).get_url_path(more=more,
                                                    add_prefix=add_prefix)

    def get_detail_url(self, action=None):
        # Reverse URLs for 'detail', 'details.record', etc.
        return reverse(('detail.%s' % action) if action else 'detail',
                       args=[self.app_slug])

    def get_dev_url(self, action='edit', args=None, prefix_only=False):
        # Either link to the "new" Marketplace Developer Hub or the old one.
        args = args or []
        prefix = ('mkt.developers' if getattr(settings, 'MARKETPLACE', False)
                  else 'devhub')
        view_name = ('%s.%s' if prefix_only else '%s.apps.%s')
        return reverse(view_name % (prefix, action),
                       args=[self.app_slug] + args)

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
    def device_types(self):
        return [d.device_type for d in
                self.addondevicetype_set.order_by('device_type__id')]

    @property
    def origin(self):
        parsed = urlparse.urlparse(self.manifest_url)
        return '%s://%s' % (parsed.scheme, parsed.netloc)

    def get_latest_file(self):
        """Get the latest file from the current version."""
        cur = self.current_version
        if cur:
            res = cur.files.order_by('-created')
            if res:
                return res[0]

    def has_icon_in_manifest(self):
        data = self.get_manifest_json()
        return 'icons' in data

    def get_manifest_json(self):
        try:
            # The first file created for each version of the web app
            # is the manifest.
            with open(self.get_latest_file().file_path, 'r') as mf:
                return json.load(mf)
        except Exception, e:
            log.error('Failed to open saved manifest %r for webapp %s, %s.'
                      % (self.manifest_url, self.pk, e))
            raise

    def share_url(self):
        return reverse('apps.share', args=[self.app_slug])

    def get_receipt(self, user):
        """Gets the receipt for the user for this webapp, or None."""
        try:
            return self.installed.get(user=user).receipt
        except Installed.DoesNotExist:
            return

    def manifest_updated(self, manifest):
        """The manifest has updated, create a version and file."""
        with open(manifest) as fh:
            chunks = fh.read()

        # We'll only create a file upload when we detect that the manifest
        # has changed, otherwise we'll be creating an awful lot of these.
        upload = FileUpload.from_post(chunks, manifest, len(chunks))
        # This does most of the heavy work.
        Version.from_upload(upload, self,
                            [Platform.objects.get(id=amo.PLATFORM_ALL.id)])
        # Triggering this ensures that the current_version gets updated.
        self.update_version()
        amo.log(amo.LOG.MANIFEST_UPDATED, self)

    def mark_done(self):
        """When the submission process is done, update status accordingly."""
        self.update(status=amo.WEBAPPS_UNREVIEWED_STATUS)


# Pull all translated_fields from Addon over to Webapp.
Webapp._meta.translated_fields = Addon._meta.translated_fields


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='mkt.webapps.index')
models.signals.post_save.connect(update_name_table, sender=Webapp,
                                 dispatch_uid='mkt.webapps.update.name.table')


class Installed(amo.models.ModelBase):
    """Track WebApp installations."""
    addon = models.ForeignKey('addons.Addon', related_name='installed')
    user = models.ForeignKey('users.UserProfile')
    # This is the email used by user at the time of installation.
    # It might be the real email, or a pseudonym, this is what will be going
    # into the receipt for verification later.
    email = models.CharField(max_length=255, db_index=True)
    # Because the addon could change between free and premium,
    # we need to store the state at time of install here.
    premium_type = models.PositiveIntegerField(
                                    choices=amo.ADDON_PREMIUM_TYPES.items(),
                                    null=True, default=None)

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user')

    @property
    def receipt(self):
        if self.addon.is_webapp():
            return create_receipt(self.pk)
        return ''


@receiver(models.signals.post_save, sender=Installed)
def add_email(sender, **kw):
    if not kw.get('raw'):
        install = kw['instance']
        if not install.email and install.premium_type == None:
            install.email = install.user.email
            install.premium_type = install.addon.premium_type
            install.save()


@memoize(prefix='create-receipt', time=60 * 10)
def create_receipt(installed_pk):
    installed = Installed.objects.get(pk=installed_pk)
    addon_pk = installed.addon.pk
    verify = '%s%s' % (settings.WEBAPPS_RECEIPT_URL, addon_pk)
    detail = reverse('users.purchases.receipt', args=[addon_pk])
    receipt = dict(typ='purchase-receipt',
                   product={'url': installed.addon.origin,
                            'storedata': urlencode({'id': int(addon_pk)})},
                   user={'type': 'email',
                         'value': installed.email},
                   iss=settings.SITE_URL,
                   nbf=time.mktime(installed.created.timetuple()),
                   iat=time.time(),
                   detail=absolutify(detail),
                   verify=absolutify(verify))
    return jwt.encode(receipt, get_key(), u'RS512')


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
