# -*- coding: utf-8 -*-
import os

import django.dispatch
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db import models

import caching.base
import commonware.log
import jinja2
import waffle

import addons.query
import amo
import amo.models
import amo.utils
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from files import utils
from files.models import File, Platform, cleanup_file
from tower import ugettext as _
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField)
from users.models import UserProfile

from .compare import version_dict, version_int

log = commonware.log.getLogger('z.versions')


class VersionManager(amo.models.ManagerBase):

    def __init__(self, include_deleted=False):
        amo.models.ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_query_set(self):
        qs = super(VersionManager, self).get_query_set()
        qs = qs._clone(klass=addons.query.IndexQuerySet)
        if not self.include_deleted:
            qs = qs.exclude(deleted=True)
        return qs.transform(Version.transformer)


class Version(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='versions')
    license = models.ForeignKey('License', null=True)
    releasenotes = PurifiedField()
    approvalnotes = models.TextField(default='', null=True)
    version = models.CharField(max_length=255, default='0.1')
    version_int = models.BigIntegerField(null=True, editable=False)

    nomination = models.DateTimeField(null=True)
    reviewed = models.DateTimeField(null=True)

    has_info_request = models.BooleanField(default=False)
    has_editor_comment = models.BooleanField(default=False)

    deleted = models.BooleanField(default=False)

    objects = VersionManager()
    with_deleted = VersionManager(include_deleted=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions'
        ordering = ['-created', '-modified']

    def __init__(self, *args, **kwargs):
        super(Version, self).__init__(*args, **kwargs)
        self.__dict__.update(version_dict(self.version or ''))

    def __unicode__(self):
        return jinja2.escape(self.version)

    def save(self, *args, **kw):
        if not self.version_int and self.version:
            v_int = version_int(self.version)
            # Magic number warning, this is the maximum size
            # of a big int in MySQL to prevent version_int overflow, for
            # people who have rather crazy version numbers.
            # http://dev.mysql.com/doc/refman/5.5/en/numeric-types.html
            if v_int < 9223372036854775807:
                self.version_int = v_int
            else:
                log.error('No version_int written for version %s, %s' %
                          (self.pk, self.version))
        return super(Version, self).save(*args, **kw)

    @classmethod
    def from_upload(cls, upload, addon, platforms, send_signal=True):
        data = utils.parse_addon(upload, addon)
        try:
            license = addon.versions.latest().license_id
        except Version.DoesNotExist:
            license = None
        v = cls.objects.create(addon=addon, version=data['version'],
                               license_id=license)
        log.info('New version: %r (%s) from %r' % (v, v.id, upload))
        # appversions
        AV = ApplicationsVersions
        for app in data.get('apps', []):
            AV(version=v, min=app.min, max=app.max,
               application_id=app.id).save()
        if addon.type in [amo.ADDON_SEARCH, amo.ADDON_WEBAPP]:
            # Search extensions and webapps are always for all platforms.
            platforms = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]
        else:
            platforms = cls._make_safe_platform_files(platforms)

        for platform in platforms:
            f = File.from_upload(upload, v, platform, parse_data=data)
            if addon.type == amo.ADDON_WEBAPP and addon.is_packaged:
                f.inject_ids()

        v.disable_old_files()
        # After the upload has been copied to all platforms, remove the upload.
        storage.delete(upload.path)
        if send_signal:
            version_uploaded.send(sender=v)

        # If packaged app and app is blocked, put in escalation queue.
        if (addon.is_webapp() and addon.is_packaged and
            addon.status == amo.STATUS_BLOCKED):
            # To avoid circular import.
            from editors.models import EscalationQueue
            EscalationQueue.objects.create(addon=addon)

        return v

    @classmethod
    def _make_safe_platform_files(cls, platforms):
        """Make file platform translations until all download pages
        support desktop ALL + mobile ALL. See bug 646268.
        """
        pl_set = set([p.id for p in platforms])

        if pl_set == set([amo.PLATFORM_ALL_MOBILE.id, amo.PLATFORM_ALL.id]):
            # Make it really ALL:
            return [Platform.objects.get(id=amo.PLATFORM_ALL.id)]

        has_mobile = any(p in amo.MOBILE_PLATFORMS for p in pl_set)
        has_desktop = any(p in amo.DESKTOP_PLATFORMS for p in pl_set)
        has_all = any(p in (amo.PLATFORM_ALL_MOBILE.id,
                            amo.PLATFORM_ALL.id) for p in pl_set)
        is_mixed = has_mobile and has_desktop
        if (is_mixed and has_all) or has_mobile:
            # Mixing desktop and mobile w/ ALL is not safe;
            # we have to split the files into exact platforms.
            # Additionally, it is not safe to use all-mobile.
            new_plats = []
            for p in platforms:
                if p.id == amo.PLATFORM_ALL_MOBILE.id:
                    new_plats.extend(list(Platform.objects
                                     .filter(id__in=amo.MOBILE_PLATFORMS)
                                     .exclude(id=amo.PLATFORM_ALL_MOBILE.id)))
                elif p.id == amo.PLATFORM_ALL.id:
                    new_plats.extend(list(Platform.objects
                                     .filter(id__in=amo.DESKTOP_PLATFORMS)
                                     .exclude(id=amo.PLATFORM_ALL.id)))
                else:
                    new_plats.append(p)
            return new_plats

        # Platforms are safe as is
        return platforms

    @property
    def path_prefix(self):
        return os.path.join(settings.ADDONS_PATH, str(self.addon_id))

    @property
    def mirror_path_prefix(self):
        return os.path.join(settings.MIRROR_STAGE_PATH, str(self.addon_id))

    def license_url(self, impala=False):
        return reverse('addons.license', args=[self.addon.slug, self.version])

    def flush_urls(self):
        return self.addon.flush_urls()

    def get_url_path(self):
        return reverse('addons.versions', args=[self.addon.slug, self.version])

    def delete(self):
        log.info(u'Version deleted: %r (%s)' % (self, self.id))
        amo.log(amo.LOG.DELETE_VERSION, self.addon, str(self.version))
        if settings.MARKETPLACE:
            self.update(deleted=True)
            if self.addon.is_packaged:
                f = self.all_files[0]
                # Unlink signed packages if packaged app.
                storage.delete(f.signed_file_path)
                log.info(u'Unlinked file: %s' % f.signed_file_path)
                storage.delete(f.signed_reviewer_file_path)
                log.info(u'Unlinked file: %s' % f.signed_reviewer_file_path)

        else:
            super(Version, self).delete()

    @property
    def current_queue(self):
        """Return the current queue, or None if not in a queue."""
        from editors.models import (ViewPendingQueue, ViewFullReviewQueue,
                                    ViewPreliminaryQueue)

        if self.addon.status in [amo.STATUS_NOMINATED,
                                 amo.STATUS_LITE_AND_NOMINATED]:
            return ViewFullReviewQueue
        elif self.addon.status == amo.STATUS_PUBLIC:
            return ViewPendingQueue
        elif self.addon.status in [amo.STATUS_LITE, amo.STATUS_UNREVIEWED]:
            return ViewPreliminaryQueue

        return None

    @amo.cached_property(writable=True)
    def all_activity(self):
        from devhub.models import VersionLog  # yucky
        al = (VersionLog.objects.filter(version=self.id).order_by('created')
              .select_related(depth=1).no_cache())
        return al

    @amo.cached_property(writable=True)
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationVersion}."""
        avs = self.apps.select_related(depth=1)
        return self._compat_map(avs)

    @amo.cached_property
    def compatible_apps_ordered(self):
        apps = self.compatible_apps.items()
        return sorted(apps, key=lambda v: v[0].short)

    def compatible_platforms(self):
        """Returns a dict of compatible file platforms for this version.

        The result is based on which app(s) the version targets.
        """
        apps = set([a.application.id for a in self.apps.all()])
        targets_mobile = amo.MOBILE.id in apps
        targets_other = any((a != amo.MOBILE.id) for a in apps)
        all_plats = {}
        if targets_other:
            all_plats.update(amo.DESKTOP_PLATFORMS)
        if targets_mobile:
            all_plats.update(amo.MOBILE_PLATFORMS)
        return all_plats

    @amo.cached_property
    def is_compatible(self):
        """Returns tuple of compatibility and reasons why if not.

        Server side conditions for determining compatibility are:
            * The add-on is an extension (not a theme, app, etc.)
            * Has not opted in to strict compatibility.
            * Does not use binary_components in chrome.manifest.

        Note: The lowest maxVersion compat check needs to be checked
              separately.
        Note: This does not take into account the client conditions.

        """
        compat = True
        reasons = []
        if self.addon.type != amo.ADDON_EXTENSION:
            compat = False
            # TODO: We may want this. For now we think it may be confusing.
            # reasons.append(_('Add-on is not an extension.'))
        if self.files.filter(binary_components=True).exists():
            compat = False
            reasons.append(_('Add-on uses binary components.'))
        if self.files.filter(strict_compatibility=True).exists():
            compat = False
            reasons.append(_('Add-on has opted into strict compatibility '
                             'checking.'))
        return (compat, reasons)

    def is_compatible_app(self, app):
        """Returns True if the provided app passes compatibility conditions."""
        appversion = self.compatible_apps.get(app)
        if appversion and app.id in amo.D2C_MAX_VERSIONS:
            return (version_int(appversion.max.version) >=
                    version_int(amo.D2C_MAX_VERSIONS.get(app.id, '*')))
        return False

    def compat_override_app_versions(self):
        """Returns the incompatible app versions range(s).

        If not ranges, returns empty list.  Otherwise, this will return all
        the app version ranges that this particular version is incompatible
        with.

        """
        from addons.models import CompatOverride
        cos = CompatOverride.objects.filter(addon=self.addon)
        if not cos:
            return []
        app_versions = []
        for co in cos:
            for range in co.collapsed_ranges():
                if (version_int(range.min) <= version_int(self.version)
                                           <= version_int(range.max)):
                    app_versions.extend([(a.min, a.max) for a in range.apps])
        return app_versions

    @amo.cached_property(writable=True)
    def all_files(self):
        """Shortcut for list(self.files.all()).  Heavily cached."""
        return list(self.files.all())

    @amo.cached_property
    def supported_platforms(self):
        """Get a list of supported platform names."""
        return list(set(amo.PLATFORMS[f.platform_id] for f in self.all_files))

    @property
    def status(self):
        if settings.MARKETPLACE and self.deleted:
            return [amo.STATUS_CHOICES[amo.STATUS_DELETED]]
        else:
            return [amo.STATUS_CHOICES[f.status] for f in self.all_files]

    @property
    def statuses(self):
        """Unadulterated statuses, good for an API."""
        return [(f.id, f.status) for f in self.all_files]

    def is_allowed_upload(self):
        """Check that a file can be uploaded based on the files
        per platform for that type of addon."""

        num_files = len(self.all_files)
        if self.addon.type == amo.ADDON_SEARCH:
            return num_files == 0
        elif num_files == 0:
            return True
        elif amo.PLATFORM_ALL in self.supported_platforms:
            return False
        elif amo.PLATFORM_ALL_MOBILE in self.supported_platforms:
            return False
        else:
            compatible = (v for k, v in self.compatible_platforms().items()
                          if k not in (amo.PLATFORM_ALL.id,
                                       amo.PLATFORM_ALL_MOBILE.id))
            return bool(set(compatible) - set(self.supported_platforms))

    @property
    def has_files(self):
        return bool(self.all_files)

    @property
    def is_unreviewed(self):
        return filter(lambda f: f.status in amo.UNREVIEWED_STATUSES,
                      self.all_files)

    @property
    def is_all_unreviewed(self):
        return not bool([f for f in self.all_files if f.status not in
                         amo.UNREVIEWED_STATUSES])

    @property
    def is_beta(self):
        return filter(lambda f: f.status == amo.STATUS_BETA, self.all_files)

    @property
    def is_lite(self):
        return filter(lambda f: f.status in amo.LITE_STATUSES, self.all_files)

    @property
    def is_jetpack(self):
        return all(f.jetpack_version for f in self.all_files)

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

    @classmethod
    def transformer_activity(cls, versions):
        """Attach all the activity to the versions."""
        from devhub.models import VersionLog  # yucky

        ids = set(v.id for v in versions)
        if not versions:
            return

        al = (VersionLog.objects.filter(version__in=ids).order_by('created')
              .select_related(depth=1).no_cache())

        def rollup(xs):
            groups = amo.utils.sorted_groupby(xs, 'version_id')
            return dict((k, list(vs)) for k, vs in groups)

        al_dict = rollup(al)

        for version in versions:
            v_id = version.id
            version.all_activity = al_dict.get(v_id, [])

    def disable_old_files(self):
        if not self.files.filter(status=amo.STATUS_BETA).exists():
            qs = File.objects.filter(version__addon=self.addon_id,
                                     version__lt=self.id,
                                     version__deleted=False,
                                     status__in=[amo.STATUS_UNREVIEWED,
                                                 amo.STATUS_PENDING])
            # Use File.update so signals are triggered.
            for f in qs:
                f.update(status=amo.STATUS_DISABLED)


def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.addon.update_status(using='default')
            instance.addon.update_version()
        except models.ObjectDoesNotExist:
            pass


def inherit_nomination(sender, instance, **kw):
    """For new versions pending review, ensure nomination date
    is inherited from last nominated version.
    """
    if kw.get('raw'):
        return
    if (instance.nomination is None
        and instance.addon.status in (amo.STATUS_NOMINATED,
                                      amo.STATUS_LITE_AND_NOMINATED)
        and not instance.is_beta):
        last_ver = (Version.objects.filter(addon=instance.addon)
                    .exclude(nomination=None).order_by('-nomination'))
        if last_ver.exists():
            instance.update(nomination=last_ver[0].nomination)


def update_incompatible_versions(sender, instance, **kw):
    """When a new version is added or deleted, send to task to update if it
    matches any compat overrides.
    """
    try:
        if not instance.addon.type == amo.ADDON_EXTENSION:
            return
    except ObjectDoesNotExist:
        return

    from addons import tasks
    tasks.update_incompatible_appversions.delay([instance.id])


def cleanup_version(sender, instance, **kw):
    """On delete of the version object call the file delete and signals."""
    if kw.get('raw'):
        return
    for file_ in instance.files.all():
        cleanup_file(file_.__class__, file_)


def clear_compatversion_cache_on_save(sender, instance, created, **kw):
    """Clears compatversion cache if new Version created."""
    if not instance.addon.type == amo.ADDON_EXTENSION:
        return

    if not kw.get('raw') and created:
        instance.addon.invalidate_d2c_versions()


def clear_compatversion_cache_on_delete(sender, instance, **kw):
    """Clears compatversion cache when Version deleted."""
    try:
        if not instance.addon.type == amo.ADDON_EXTENSION:
            return
    except ObjectDoesNotExist:
        return

    if not kw.get('raw'):
        instance.addon.invalidate_d2c_versions()


version_uploaded = django.dispatch.Signal()
models.signals.post_save.connect(update_status, sender=Version,
                                 dispatch_uid='version_update_status')
models.signals.post_save.connect(inherit_nomination, sender=Version,
                                 dispatch_uid='version_inherit_nomination')
models.signals.post_delete.connect(update_status, sender=Version,
                                   dispatch_uid='version_update_status')
models.signals.post_save.connect(update_incompatible_versions, sender=Version,
                                 dispatch_uid='version_update_incompat')
models.signals.post_delete.connect(update_incompatible_versions,
                                   sender=Version,
                                   dispatch_uid='version_update_incompat')
models.signals.pre_delete.connect(cleanup_version, sender=Version,
                                  dispatch_uid='cleanup_version')
models.signals.post_save.connect(clear_compatversion_cache_on_save,
                                 sender=Version,
                                 dispatch_uid='clear_compatversion_cache_save')
models.signals.post_delete.connect(clear_compatversion_cache_on_delete,
                                   sender=Version,
                                   dispatch_uid='clear_compatversion_cache_del')


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
        if (waffle.switch_is_active('d2c-buttons') and
            self.version.is_compatible[0] and
            self.version.is_compatible_app(amo.APP_IDS[self.application.id])):
            return _(u'{app} {min} and later').format(app=self.application,
                                                      min=self.min)
        return u'%s %s - %s' % (self.application, self.min, self.max)
