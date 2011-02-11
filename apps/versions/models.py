# -*- coding: utf-8 -*-
import os

from django.conf import settings
from django.db import models
import jinja2

import commonware.log
import caching.base

import amo
import amo.models
import amo.utils
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from files import utils
from files.models import File, Platform
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField)
from users.models import UserProfile

from . import compare

log = commonware.log.getLogger('z.versions')


class Version(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='versions')
    license = models.ForeignKey('License', null=True)
    releasenotes = PurifiedField()
    approvalnotes = models.TextField(default='', null=True)
    version = models.CharField(max_length=255, default='0.1')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions'
        ordering = ['-created', '-modified']

    def __init__(self, *args, **kwargs):
        super(Version, self).__init__(*args, **kwargs)
        self.__dict__.update(compare.version_dict(self.version or ''))

    def __unicode__(self):
        return jinja2.escape(self.version)

    @classmethod
    def from_upload(cls, upload, addon, platforms):
        data = utils.parse_addon(upload.path, addon)
        try:
            license = addon.versions.latest().license_id
        except Version.DoesNotExist:
            license = None
        v = cls.objects.create(addon=addon, version=data['version'],
                               license_id=license)
        log.debug('New version: %r (%s) from %r' % (v, v.id, upload))
        # appversions
        AV = ApplicationsVersions
        for app in data.get('apps', []):
            AV(version=v, min=app.min, max=app.max,
               application_id=app.id).save()
        if addon.type == amo.ADDON_SEARCH:
            # Search extensions are always for all platforms.
            platforms = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]
        for platform in platforms:
            File.from_upload(upload, v, platform, parse_data=data)
        # After the upload has been copied to all
        # platforms, remove the upload.
        upload.path.unlink()
        return v

    @property
    def path_prefix(self):
        return os.path.join(settings.ADDONS_PATH, str(self.addon_id))

    @property
    def mirror_path_prefix(self):
        return os.path.join(settings.MIRROR_STAGE_PATH, str(self.addon_id))

    def license_url(self):
        return reverse('addons.license', args=[self.addon.slug, self.version])

    def flush_urls(self):
        return self.addon.flush_urls()

    def get_url_path(self):
        return reverse('addons.versions', args=[self.addon.slug, self.version])

    def delete(self):
        amo.log(amo.LOG.DELETE_VERSION, self.addon, str(self.version))
        super(Version, self).delete()

    @amo.cached_property(writable=True)
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationVersion}."""
        avs = self.apps.select_related(depth=1)
        return self._compat_map(avs)

    @amo.cached_property(writable=True)
    def all_files(self):
        """Shortcut for list(self.files.all()).  Heavily cached."""
        return list(self.files.all())

    # TODO(jbalogh): Do we want names or Platforms?
    @amo.cached_property
    def supported_platforms(self):
        """Get a list of supported platform names."""
        return list(set(amo.PLATFORMS[f.platform_id]
                        for f in self.all_files))

    def is_allowed_upload(self):
        """Check that a file can be uploaded based on the files
        per platform for that type of addon."""
        if self.addon.type == amo.ADDON_SEARCH:
            return not bool(len(self.all_files))
        elif amo.PLATFORM_ALL in self.supported_platforms:
            return False
        else:
            available = amo.SUPPORTED_PLATFORMS.values()
            available.remove(amo.PLATFORM_ALL)
            return bool(set(available) - set(self.supported_platforms))

    @property
    def has_files(self):
        return bool(self.all_files)

    @property
    def is_unreviewed(self):
        return filter(lambda f: f.status in amo.UNREVIEWED_STATUSES,
                      self.all_files)

    @property
    def is_beta(self):
        return filter(lambda f: f.status == amo.STATUS_BETA, self.all_files)

    @property
    def is_lite(self):
        return filter(lambda f: f.status in amo.LITE_STATUSES, self.all_files)

    @classmethod
    def _compat_map(cls, avs):
        apps = {}
        for av in avs:
            app_id = av.application_id
            if app_id in amo.APP_IDS:
                apps[amo.APP_IDS[app_id]] = av
        return apps

    @classmethod
    def transformer(cls, versions):
        """Attach all the compatible apps and files to the versions."""
        ids = set(v.id for v in versions)
        if not versions:
            return

        avs = (ApplicationsVersions.objects.filter(version__in=ids)
               .select_related(depth=1).no_cache())
        files = (File.objects.filter(version__in=ids)
                 .select_related('version').no_cache())

        def rollup(xs):
            groups = amo.utils.sorted_groupby(xs, 'version_id')
            return dict((k, list(vs)) for k, vs in groups)

        av_dict, file_dict = rollup(avs), rollup(files)

        for version in versions:
            v_id = version.id
            version.compatible_apps = cls._compat_map(av_dict.get(v_id, []))
            version.all_files = file_dict.get(v_id, [])


def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.addon.update_status(using='default')
            instance.addon.update_current_version()
        except models.ObjectDoesNotExist:
            pass
        if kw.get('created'):
            # Disable older unreviewed files for this add-on.
            qs = File.objects.filter(version__addon=instance.addon_id,
                                     version__lt=instance,
                                     status=amo.STATUS_UNREVIEWED)
            # Use File.update so signals are triggered.
            for f in qs:
                f.update(status=amo.STATUS_DISABLED)


models.signals.post_save.connect(update_status, sender=Version,
                                 dispatch_uid='version_update_status')
models.signals.post_delete.connect(update_status, sender=Version,
                                   dispatch_uid='version_update_status')


class LicenseManager(amo.models.ManagerBase):

    def builtins(self):
        return self.filter(builtin__gt=0).order_by('builtin')


class License(amo.models.ModelBase):
    OTHER = 0

    name = TranslatedField(db_column='name')
    url = models.URLField(null=True, verify_exists=False)
    builtin = models.PositiveIntegerField(default=OTHER)
    text = LinkifiedField()
    on_form = models.BooleanField(default=False,
        help_text='Is this a license choice in the devhub?')
    some_rights = models.BooleanField(default=False,
        help_text='Show "Some Rights Reserved" instead of the license name?')
    icons = models.CharField(max_length=255, null=True,
        help_text='Space-separated list of icon identifiers.')

    objects = LicenseManager()

    class Meta:
        db_table = 'licenses'

    def __unicode__(self):
        return unicode(self.name)


class VersionComment(amo.models.ModelBase):
    """Editor comments for version discussion threads."""
    version = models.ForeignKey(Version)
    user = models.ForeignKey(UserProfile)
    reply_to = models.ForeignKey(Version, related_name="reply_to",
                                 db_column='reply_to', null=True)
    subject = models.CharField(max_length=1000)
    comment = models.TextField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versioncomments'


class VersionSummary(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    version = models.ForeignKey(Version)
    application = models.ForeignKey(Application)
    min = models.IntegerField(null=True)
    max = models.IntegerField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions_summary'


class ApplicationsVersions(caching.base.CachingMixin, models.Model):

    application = models.ForeignKey(Application)
    version = models.ForeignKey(Version, related_name='apps')
    min = models.ForeignKey(AppVersion, db_column='min',
        related_name='min_set')
    max = models.ForeignKey(AppVersion, db_column='max',
        related_name='max_set')

    objects = caching.base.CachingManager()

    class Meta:
        db_table = u'applications_versions'
        unique_together = (("application", "version"),)

    def __unicode__(self):
        return u'%s %s - %s' % (self.application, self.min, self.max)
