# -*- coding: utf-8 -*-
import datetime
import os

import django.dispatch
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db import models

import caching.base
import commonware.log
import jinja2
from django_statsd.clients import statsd
from tower import ugettext as _

import addons.query
import amo
import amo.models
import amo.utils
from amo.decorators import use_master
from amo.urlresolvers import reverse
from amo.helpers import user_media_path, id_to_path
from amo.utils import utc_millesecs_from_epoch
from applications.models import AppVersion
from files import utils
from files.models import File, cleanup_file
from translations.fields import (LinkifiedField, PurifiedField, save_signal,
                                 TranslatedField)
from users.models import UserProfile

from .compare import version_dict, version_int

log = commonware.log.getLogger('z.versions')

VALID_SOURCE_EXTENSIONS = (
    '.zip', '.tar', '.7z', '.tar.gz', '.tgz', '.tbz', '.txz', '.tar.bz2',
    '.tar.xz'
)


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


def source_upload_path(instance, filename):
    # At this point we already know that ext is one of VALID_SOURCE_EXTENSIONS
    # because we already checked for that in
    # /apps/devhub/forms.py#WithSourceMixin.clean_source.
    for ext in VALID_SOURCE_EXTENSIONS:
        if filename.endswith(ext):
            break

    return os.path.join(
        u'version_source',
        id_to_path(instance.pk),
        u'{0}-{1}-src{2}'.format(
            instance.addon.slug,
            instance.version,
            ext)
    )


class Version(amo.models.OnChangeMixin, amo.models.ModelBase):
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

    supported_locales = models.CharField(max_length=255)

    _developer_name = models.CharField(max_length=255, default='',
                                       editable=False)

    source = models.FileField(
        upload_to=source_upload_path, null=True, blank=True)

    # The order of those managers is very important: please read the lengthy
    # comment above the Addon managers declaration/instanciation.
    unfiltered = VersionManager(include_deleted=True)
    objects = VersionManager()

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
        super(Version, self).save(*args, **kw)
        return self

    @classmethod
    def from_upload(cls, upload, addon, platforms, send_signal=True,
                    source=None, is_beta=False):
        data = utils.parse_addon(upload, addon)
        try:
            license = addon.versions.latest().license_id
        except Version.DoesNotExist:
            license = None
        max_len = cls._meta.get_field_by_name('_developer_name')[0].max_length
        developer = data.get('developer_name', '')[:max_len]
        v = cls.objects.create(
            addon=addon,
            version=data['version'],
            license_id=license,
            _developer_name=developer,
            source=source
        )
        log.info('New version: %r (%s) from %r' % (v, v.id, upload))

        AV = ApplicationsVersions
        for app in data.get('apps', []):
            AV(version=v, min=app.min, max=app.max,
               application=app.id).save()
        if addon.type == amo.ADDON_SEARCH:
            # Search extensions are always for all platforms.
            platforms = [amo.PLATFORM_ALL.id]
        else:
            platforms = cls._make_safe_platform_files(platforms)

        for platform in platforms:
            File.from_upload(upload, v, platform, parse_data=data,
                             is_beta=is_beta)

        v.disable_old_files()
        # After the upload has been copied to all platforms, remove the upload.
        storage.delete(upload.path)
        if send_signal:
            version_uploaded.send(sender=v)

        # Track the time it took from first upload through validation
        # (and whatever else) until a version was created.
        upload_start = utc_millesecs_from_epoch(upload.created)
        now = datetime.datetime.now()
        now_ts = utc_millesecs_from_epoch(now)
        upload_time = now_ts - upload_start

        log.info('Time for version {version} creation from upload: {delta}; '
                 'created={created}; now={now}'
                 .format(delta=upload_time, version=v,
                         created=upload.created, now=now))
        statsd.timing('devhub.version_created_from_upload', upload_time)

        return v

    @classmethod
    def _make_safe_platform_files(cls, platforms):
        """Make file platform translations until all download pages
        support desktop ALL + mobile ALL. See bug 646268.

        Returns platforms ids.
        """
        pl_set = set(platforms)

        if pl_set == set((amo.PLATFORM_ALL.id,)):
            # Make it really ALL:
            return [amo.PLATFORM_ALL.id]

        has_mobile = amo.PLATFORM_ANDROID in pl_set
        has_desktop = any(p in amo.DESKTOP_PLATFORMS for p in pl_set)
        has_all = amo.PLATFORM_ALL in pl_set
        is_mixed = has_mobile and has_desktop
        if (is_mixed and has_all) or has_mobile:
            # Mixing desktop and mobile w/ ALL is not safe;
            # we have to split the files into exact platforms.
            new_plats = []
            for platform in platforms:
                if platform == amo.PLATFORM_ALL.id:
                    plats = amo.DESKTOP_PLATFORMS.keys()
                    plats.remove(amo.PLATFORM_ALL.id)
                    new_plats.extend(plats)
                else:
                    new_plats.append(platform)
            return new_plats

        # Platforms are safe as is
        return platforms

    @property
    def path_prefix(self):
        return os.path.join(user_media_path('addons'), str(self.addon_id))

    @property
    def mirror_path_prefix(self):
        return os.path.join(user_media_path('addons'), str(self.addon_id))

    def license_url(self, impala=False):
        return reverse('addons.license', args=[self.addon.slug, self.version])

    def flush_urls(self):
        return self.addon.flush_urls()

    def get_url_path(self):
        if not self.addon.is_listed:  # Not listed? Doesn't have a public page.
            return ''
        return reverse('addons.versions', args=[self.addon.slug, self.version])

    def delete(self):
        log.info(u'Version deleted: %r (%s)' % (self, self.id))
        amo.log(amo.LOG.DELETE_VERSION, self.addon, str(self.version))
        super(Version, self).delete()

    @property
    def current_queue(self):
        """Return the current queue, or None if not in a queue."""
        from editors.models import (ViewFullReviewQueue,
                                    ViewPendingQueue,
                                    ViewPreliminaryQueue,
                                    ViewUnlistedFullReviewQueue,
                                    ViewUnlistedPendingQueue,
                                    ViewUnlistedPreliminaryQueue)

        if self.addon.status in [amo.STATUS_NOMINATED,
                                 amo.STATUS_LITE_AND_NOMINATED]:
            return (ViewFullReviewQueue if self.addon.is_listed
                    else ViewUnlistedFullReviewQueue)
        elif self.addon.status == amo.STATUS_PUBLIC:
            return (ViewPendingQueue if self.addon.is_listed
                    else ViewUnlistedPendingQueue)
        elif self.addon.status in [amo.STATUS_LITE, amo.STATUS_UNREVIEWED]:
            return (ViewPreliminaryQueue if self.addon.is_listed
                    else ViewUnlistedPreliminaryQueue)

        return None

    @amo.cached_property(writable=True)
    def all_activity(self):
        from devhub.models import VersionLog  # yucky
        al = (VersionLog.objects.filter(version=self.id).order_by('created')
              .select_related('activity_log', 'version').no_cache())
        return al

    @amo.cached_property(writable=True)
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationVersion}."""
        avs = self.apps.select_related('versions', 'license')
        return self._compat_map(avs)

    @amo.cached_property
    def compatible_apps_ordered(self):
        apps = self.compatible_apps.items()
        return sorted(apps, key=lambda v: v[0].short)

    def compatible_platforms(self):
        """Returns a dict of compatible file platforms for this version.

        The result is based on which app(s) the version targets.
        """
        app_ids = [a.application for a in self.apps.all()]
        targets_mobile = amo.ANDROID.id in app_ids
        targets_other = any((id_ != amo.ANDROID.id) for id_ in app_ids)
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
        return list(set(amo.PLATFORMS[f.platform] for f in self.all_files))

    @property
    def status(self):
        return [f.STATUS_CHOICES[f.status] for f in self.all_files]

    @property
    def statuses(self):
        """Unadulterated statuses, good for an API."""
        return [(f.id, f.status) for f in self.all_files]

    def is_allowed_upload(self):
        """
        Check that a file can be uploaded based on the files
        per platform for that type of addon.
        """
        num_files = len(self.all_files)
        if self.addon.type == amo.ADDON_SEARCH:
            return num_files == 0
        elif num_files == 0:
            return True
        elif amo.PLATFORM_ALL in self.supported_platforms:
            return False
        else:
            compatible = (v for k, v in self.compatible_platforms().items()
                          if k != amo.PLATFORM_ALL.id)
            return bool(set(compatible) - set(self.supported_platforms))

    def is_public(self):
        # To be public, a version must not be deleted, must belong to a public
        # addon, and all its attached files must have public status.
        try:
            return (not self.deleted and self.addon.is_public() and
                    all(f.status == amo.STATUS_PUBLIC for f in self.all_files))
        except ObjectDoesNotExist:
            return False

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
            app_id = av.application
            if app_id in amo.APP_IDS:
                apps[amo.APP_IDS[app_id]] = av
        return apps

    @classmethod
    def transformer(cls, versions):
        """Attach all the compatible apps and files to the versions."""
        ids = set(v.id for v in versions)
        if not versions:
            return

        # FIXME: find out why we have no_cache() here and try to remove it.
        avs = (ApplicationsVersions.objects.filter(version__in=ids)
               .select_related('application', 'apps', 'min_set', 'max_set')
               .no_cache())
        files = File.objects.filter(version__in=ids).no_cache()

        def rollup(xs):
            groups = amo.utils.sorted_groupby(xs, 'version_id')
            return dict((k, list(vs)) for k, vs in groups)

        av_dict, file_dict = rollup(avs), rollup(files)

        for version in versions:
            v_id = version.id
            version.compatible_apps = cls._compat_map(av_dict.get(v_id, []))
            version.all_files = file_dict.get(v_id, [])
            for f in version.all_files:
                f.version = version

    @classmethod
    def transformer_activity(cls, versions):
        """Attach all the activity to the versions."""
        from devhub.models import VersionLog  # yucky

        ids = set(v.id for v in versions)
        if not versions:
            return

        al = (VersionLog.objects.filter(version__in=ids).order_by('created')
              .select_related('activity_log', 'version').no_cache())

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

    @property
    def developer_name(self):
        return self._developer_name

    def reset_nomination_time(self, nomination=None):
        if not self.nomination or nomination:
            nomination = nomination or datetime.datetime.now()
            # We need signal=False not to call update_status (which calls us).
            self.update(nomination=nomination, _signal=False)
            # But we need the cache to be flushed.
            Version.objects.invalidate(self)

    @property
    def is_listed(self):
        return self.addon.is_listed

    @property
    def unreviewed_files(self):
        """A File is unreviewed if:
        - its status is in amo.UNDER_REVIEW_STATUSES or
        - its addon status is in amo.UNDER_REVIEW_STATUSES
          and its status is either in amo.UNDER_REVIEW_STATUSES or
          amo.STATUS_LITE
        """
        under_review_or_lite = amo.UNDER_REVIEW_STATUSES + (amo.STATUS_LITE,)
        return self.files.filter(
            models.Q(status__in=amo.UNDER_REVIEW_STATUSES) |
            models.Q(version__addon__status__in=amo.UNDER_REVIEW_STATUSES,
                     status__in=under_review_or_lite))


@Version.on_change
def watch_source(old_attr={}, new_attr={}, instance=None, sender=None, **kw):
    """Set the "admin_review" flag on the addon if a source file was added.

    Source files can be added to any upload, but it only makes sense to admin
    flag the addon if it's an extension, not a search tool, dictionary...
    """
    # Only flag extensions (bug 1200621).
    if instance.addon.type != amo.ADDON_EXTENSION:
        return
    # Only admins may review addons with source files attached.
    if old_attr.get('source') != new_attr.get('source'):
        # Imported here to avoid an import loop.
        from devhub.models import ActivityLog, VersionLog
        instance.addon.admin_review = True
        instance.addon.save()
        # Use the addons team go-to user "Mozilla".
        user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
        log = ActivityLog.objects.create(
            action=amo.LOG.REQUEST_SUPER_REVIEW.id,
            user=user,
            details={'comments': u'This version has been automatically flagged'
                                 u' as admin review, as it had some source '
                                 u'files attached when submitted.'})
        VersionLog.objects.create(version_id=instance.pk, activity_log=log)


@use_master
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.addon.update_status()
        except models.ObjectDoesNotExist:
            log.info('Got ObjectDoesNotExist processing Version change signal',
                     exc_info=True)


def inherit_nomination(sender, instance, **kw):
    """
    For new versions pending review, ensure nomination date
    is inherited from last nominated version.
    """
    if kw.get('raw'):
        return
    addon = instance.addon
    if (instance.nomination is None
            and addon.status in amo.UNDER_REVIEW_STATUSES
            and not instance.is_beta):
        last_ver = (Version.objects.filter(addon=addon)
                    .exclude(nomination=None).order_by('-nomination'))
        if last_ver.exists():
            instance.reset_nomination_time(nomination=last_ver[0].nomination)


def update_incompatible_versions(sender, instance, **kw):
    """
    When a new version is added or deleted, send to task to update if it
    matches any compat overrides.
    """
    try:
        if not instance.addon.reload().type == amo.ADDON_EXTENSION:
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
    try:
        if not instance.addon.type == amo.ADDON_EXTENSION:
            return
    except ObjectDoesNotExist:
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
models.signals.pre_save.connect(
    save_signal, sender=Version, dispatch_uid='version_translations')
models.signals.post_save.connect(
    update_status, sender=Version, dispatch_uid='version_update_status')
models.signals.post_save.connect(
    inherit_nomination, sender=Version,
    dispatch_uid='version_inherit_nomination')
models.signals.post_delete.connect(
    update_status, sender=Version, dispatch_uid='version_update_status')
models.signals.post_save.connect(
    update_incompatible_versions, sender=Version,
    dispatch_uid='version_update_incompat')
models.signals.post_delete.connect(
    update_incompatible_versions, sender=Version,
    dispatch_uid='version_update_incompat')
models.signals.pre_delete.connect(
    cleanup_version, sender=Version, dispatch_uid='cleanup_version')
models.signals.post_save.connect(
    clear_compatversion_cache_on_save, sender=Version,
    dispatch_uid='clear_compatversion_cache_save')
models.signals.post_delete.connect(
    clear_compatversion_cache_on_delete, sender=Version,
    dispatch_uid='clear_compatversion_cache_del')


class LicenseManager(amo.models.ManagerBase):

    def builtins(self):
        return self.filter(builtin__gt=0).order_by('builtin')


class License(amo.models.ModelBase):
    OTHER = 0

    name = TranslatedField(db_column='name')
    url = models.URLField(null=True)
    builtin = models.PositiveIntegerField(default=OTHER)
    text = LinkifiedField()
    on_form = models.BooleanField(
        default=False, help_text='Is this a license choice in the devhub?')
    some_rights = models.BooleanField(
        default=False,
        help_text='Show "Some Rights Reserved" instead of the license name?')
    icons = models.CharField(
        max_length=255, null=True,
        help_text='Space-separated list of icon identifiers.')

    objects = LicenseManager()

    class Meta:
        db_table = 'licenses'

    def __unicode__(self):
        return unicode(self.name)

models.signals.pre_save.connect(
    save_signal, sender=License, dispatch_uid='version_translations')


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

    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              db_column='application_id')
    version = models.ForeignKey(Version, related_name='apps')
    min = models.ForeignKey(AppVersion, db_column='min',
                            related_name='min_set')
    max = models.ForeignKey(AppVersion, db_column='max',
                            related_name='max_set')

    objects = caching.base.CachingManager()

    class Meta:
        db_table = u'applications_versions'
        unique_together = (("application", "version"),)

    def get_application_display(self):
        return unicode(amo.APPS_ALL[self.application].pretty)

    def __unicode__(self):
        if (self.version.is_compatible[0] and
                self.version.is_compatible_app(amo.APP_IDS[self.application])):
            return _(u'{app} {min} and later').format(
                app=self.get_application_display(),
                min=self.min
            )
        return u'%s %s - %s' % (self.get_application_display(),
                                self.min, self.max)
