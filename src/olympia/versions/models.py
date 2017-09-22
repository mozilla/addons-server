# -*- coding: utf-8 -*-
import datetime
import os

import django.dispatch
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db import models
from django.db.models import Q
from django.utils.functional import cached_property
from django.utils.translation import ugettext

import caching.base
import jinja2
from django_statsd.clients import statsd
from waffle import switch_is_active

import olympia.core.logger
from olympia import activity, amo
from olympia.amo.models import ManagerBase, ModelBase, OnChangeMixin
from olympia.amo.utils import sorted_groupby, utc_millesecs_from_epoch
from olympia.amo.decorators import use_master
from olympia.amo.urlresolvers import reverse
from olympia.amo.templatetags.jinja_helpers import user_media_path, id_to_path
from olympia.applications.models import AppVersion
from olympia.files import utils
from olympia.files.models import File, cleanup_file
from olympia.translations.fields import (
    LinkifiedField, PurifiedField, save_signal, TranslatedField)

from .compare import version_dict, version_int

log = olympia.core.logger.getLogger('z.versions')

VALID_SOURCE_EXTENSIONS = (
    '.zip', '.tar', '.7z', '.tar.gz', '.tgz', '.tbz', '.txz', '.tar.bz2',
    '.tar.xz'
)


class VersionManager(ManagerBase):

    def __init__(self, include_deleted=False):
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super(VersionManager, self).get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(deleted=True)
        return qs.transform(Version.transformer)

    def valid(self):
        return self.filter(
            files__status__in=amo.VALID_FILE_STATUSES).distinct()


def source_upload_path(instance, filename):
    # At this point we already know that ext is one of VALID_SOURCE_EXTENSIONS
    # because we already checked for that in
    # /src/olympia/devhub/forms.py#WithSourceMixin.clean_source.
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


class VersionCreateError(ValueError):
    pass


class Version(OnChangeMixin, ModelBase):
    addon = models.ForeignKey(
        'addons.Addon', related_name='versions', on_delete=models.CASCADE)
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

    source = models.FileField(
        upload_to=source_upload_path, null=True, blank=True)

    channel = models.IntegerField(choices=amo.RELEASE_CHANNEL_CHOICES,
                                  default=amo.RELEASE_CHANNEL_LISTED)

    # The order of those managers is very important: please read the lengthy
    # comment above the Addon managers declaration/instantiation.
    unfiltered = VersionManager(include_deleted=True)
    objects = VersionManager()

    class Meta(ModelBase.Meta):
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
    def from_upload(cls, upload, addon, platforms, channel, send_signal=True,
                    source=None, is_beta=False, parsed_data=None):
        from olympia.addons.models import AddonFeatureCompatibility

        if addon.status == amo.STATUS_DISABLED:
            raise VersionCreateError(
                'Addon is Mozilla Disabled; no new versions are allowed.')

        if parsed_data is None:
            parsed_data = utils.parse_addon(upload, addon)
        license_id = None
        if channel == amo.RELEASE_CHANNEL_LISTED:
            previous_version = addon.find_latest_version(
                channel=channel, exclude=())
            if previous_version and previous_version.license_id:
                license_id = previous_version.license_id
        version = cls.objects.create(
            addon=addon,
            version=parsed_data['version'],
            license_id=license_id,
            source=source,
            channel=channel,
        )
        log.info(
            'New version: %r (%s) from %r' % (version, version.id, upload))
        activity.log_create(amo.LOG.ADD_VERSION, version, addon)
        # Update the add-on e10s compatibility since we're creating a new
        # version that may change that.
        e10s_compatibility = parsed_data.get('e10s_compatibility')
        if e10s_compatibility is not None:
            feature_compatibility = (
                AddonFeatureCompatibility.objects.get_or_create(addon=addon)[0]
            )
            feature_compatibility.update(e10s=e10s_compatibility)

        compatible_apps = {}
        for app in parsed_data.get('apps', []):
            compatible_apps[app.appdata] = ApplicationsVersions(
                version=version, min=app.min, max=app.max, application=app.id)
            compatible_apps[app.appdata].save()

        # See #2828: sometimes when we generate the filename(s) below, in
        # File.from_upload(), cache-machine is confused and has trouble
        # fetching the ApplicationsVersions that were just created. To work
        # around this we pre-generate version.compatible_apps and avoid the
        # queries completely.
        version.compatible_apps = compatible_apps

        if addon.type == amo.ADDON_SEARCH:
            # Search extensions are always for all platforms.
            platforms = [amo.PLATFORM_ALL.id]
        else:
            platforms = cls._make_safe_platform_files(platforms)

        for platform in platforms:
            File.from_upload(upload, version, platform,
                             parsed_data=parsed_data, is_beta=is_beta)

        version.inherit_nomination(from_statuses=[amo.STATUS_AWAITING_REVIEW])
        version.disable_old_files()
        # After the upload has been copied to all platforms, remove the upload.
        storage.delete(upload.path)
        if send_signal:
            version_uploaded.send(sender=version)

        # Track the time it took from first upload through validation
        # (and whatever else) until a version was created.
        upload_start = utc_millesecs_from_epoch(upload.created)
        now = datetime.datetime.now()
        now_ts = utc_millesecs_from_epoch(now)
        upload_time = now_ts - upload_start

        log.info('Time for version {version} creation from upload: {delta}; '
                 'created={created}; now={now}'
                 .format(delta=upload_time, version=version,
                         created=upload.created, now=now))
        statsd.timing('devhub.version_created_from_upload', upload_time)

        return version

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

    def license_url(self, impala=False):
        return reverse('addons.license', args=[self.addon.slug, self.version])

    def get_url_path(self):
        if self.channel == amo.RELEASE_CHANNEL_UNLISTED:
            return ''
        return reverse('addons.versions', args=[self.addon.slug, self.version])

    def delete(self, hard=False):
        log.info(u'Version deleted: %r (%s)' % (self, self.id))
        activity.log_create(amo.LOG.DELETE_VERSION, self.addon,
                            str(self.version))
        if hard:
            super(Version, self).delete()
        else:
            # By default we soft delete so we can keep the files for comparison
            # and a record of the version number.
            self.files.update(status=amo.STATUS_DISABLED)
            self.deleted = True
            self.save()

    @property
    def is_user_disabled(self):
        return self.files.filter(status=amo.STATUS_DISABLED).exclude(
            original_status=amo.STATUS_NULL).exists()

    @is_user_disabled.setter
    def is_user_disabled(self, disable):
        # User wants to disable (and the File isn't already).
        if disable:
            for file in self.files.exclude(status=amo.STATUS_DISABLED).all():
                file.update(original_status=file.status,
                            status=amo.STATUS_DISABLED)
        # User wants to re-enable (and user did the disable, not Mozilla).
        else:
            for file in self.files.exclude(
                    original_status=amo.STATUS_NULL).all():
                file.update(status=file.original_status,
                            original_status=amo.STATUS_NULL)

    @property
    def current_queue(self):
        """Return the current queue, or None if not in a queue."""
        from olympia.editors.models import (
            ViewFullReviewQueue, ViewPendingQueue)

        if self.channel == amo.RELEASE_CHANNEL_UNLISTED:
            # Unlisted add-ons and their updates are automatically approved so
            # they don't get a queue.
            # TODO: when we've finished with unlisted/listed versions the
            # status of an all-unlisted addon will be STATUS_NULL so we won't
            # need this check.
            return None

        if self.addon.status == amo.STATUS_NOMINATED:
            return ViewFullReviewQueue
        elif self.addon.status == amo.STATUS_PUBLIC:
            return ViewPendingQueue

        return None

    @cached_property
    def all_activity(self):
        from olympia.activity.models import VersionLog  # yucky
        al = (VersionLog.objects.filter(version=self.id).order_by('created')
              .select_related('activity_log', 'version').no_cache())
        return al

    @cached_property
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationsVersions}."""
        avs = self.apps.select_related('version')
        return self._compat_map(avs)

    @cached_property
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

    @cached_property
    def is_compatible_by_default(self):
        """Returns whether or not the add-on is considered compatible by
        default."""
        return not self.files.filter(
            Q(binary_components=True) | Q(strict_compatibility=True)).exists()

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
        from olympia.addons.models import CompatOverride
        cos = CompatOverride.objects.filter(addon=self.addon)
        if not cos:
            return []
        app_versions = []
        for co in cos:
            for range in co.collapsed_ranges():
                if (version_int(range.min) <= version_int(self.version) <=
                        version_int(range.max)):
                    app_versions.extend([(a.min, a.max) for a in range.apps])
        return app_versions

    @cached_property
    def all_files(self):
        """Shortcut for list(self.files.all()).  Heavily cached."""
        return list(self.files.all())

    @cached_property
    def supported_platforms(self):
        """Get a list of supported platform names."""
        return list(set(amo.PLATFORMS[f.platform] for f in self.all_files))

    @property
    def status(self):
        return [
            f.STATUS_CHOICES.get(f.status, ugettext('[status:%s]') % f.status)
            for f in self.all_files]

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
        # We don't want new files once a review has been done.
        elif (not self.is_all_unreviewed and not self.is_beta and
              self.channel == amo.RELEASE_CHANNEL_LISTED):
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
    def is_restart_required(self):
        return any(file_.is_restart_required for file_ in self.all_files)

    @property
    def is_webextension(self):
        return any(file_.is_webextension for file_ in self.all_files)

    @property
    def is_mozilla_signed(self):
        """Is the file a special "Mozilla Signed Extension"

        See https://wiki.mozilla.org/Add-ons/InternalSigning for more details.
        We use that information to workaround compatibility limits for legacy
        add-ons and to avoid them receiving negative boosts compared to
        WebExtensions.

        See https://github.com/mozilla/addons-server/issues/6424
        """
        return all(
            file_.is_mozilla_signed_extension for file_ in self.all_files)

    @property
    def has_files(self):
        return bool(self.all_files)

    @property
    def is_unreviewed(self):
        return filter(lambda f: f.status in amo.UNREVIEWED_FILE_STATUSES,
                      self.all_files)

    @property
    def is_all_unreviewed(self):
        return not bool([f for f in self.all_files if f.status not in
                         amo.UNREVIEWED_FILE_STATUSES])

    @property
    def is_beta(self):
        return any(f for f in self.all_files if f.status == amo.STATUS_BETA)

    @property
    def is_jetpack(self):
        return all(f.jetpack_version for f in self.all_files)

    @property
    def sources_provided(self):
        return bool(self.source)

    @property
    def admin_review(self):
        return self.addon.admin_review

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
               .select_related('min', 'max')
               .no_cache())
        files = File.objects.filter(version__in=ids).no_cache()

        def rollup(xs):
            groups = sorted_groupby(xs, 'version_id')
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
        from olympia.activity.models import VersionLog  # yucky

        ids = set(v.id for v in versions)
        if not versions:
            return

        al = (VersionLog.objects.filter(version__in=ids).order_by('created')
              .select_related('activity_log', 'version').no_cache())

        def rollup(xs):
            groups = sorted_groupby(xs, 'version_id')
            return dict((k, list(vs)) for k, vs in groups)

        al_dict = rollup(al)

        for version in versions:
            v_id = version.id
            version.all_activity = al_dict.get(v_id, [])

    def disable_old_files(self):
        """
        Disable files from versions older than the current one and awaiting
        review. Used when uploading a new version.

        Does nothing if the current instance is unlisted or has beta files.
        """
        if (self.channel == amo.RELEASE_CHANNEL_LISTED and
                not self.files.filter(status=amo.STATUS_BETA).exists()):
            qs = File.objects.filter(version__addon=self.addon_id,
                                     version__lt=self.id,
                                     version__deleted=False,
                                     status__in=[amo.STATUS_AWAITING_REVIEW,
                                                 amo.STATUS_PENDING])
            # Use File.update so signals are triggered.
            for f in qs:
                f.update(status=amo.STATUS_DISABLED)

    def reset_nomination_time(self, nomination=None):
        if not self.nomination or nomination:
            nomination = nomination or datetime.datetime.now()
            # We need signal=False not to call update_status (which calls us).
            self.update(nomination=nomination, _signal=False)
            # But we need the cache to be flushed.
            Version.objects.invalidate(self)

    def inherit_nomination(self, from_statuses=None):
        last_ver = (Version.objects.filter(addon=self.addon,
                                           channel=amo.RELEASE_CHANNEL_LISTED)
                    .exclude(nomination=None).exclude(id=self.pk)
                    .order_by('-nomination'))
        if from_statuses:
            last_ver = last_ver.filter(files__status__in=from_statuses)
        if last_ver.exists():
            self.reset_nomination_time(nomination=last_ver[0].nomination)

    @property
    def unreviewed_files(self):
        """A File is unreviewed if its status is amo.STATUS_AWAITING_REVIEW."""
        return self.files.filter(status=amo.STATUS_AWAITING_REVIEW)

    @property
    def is_ready_for_auto_approval(self):
        """Return whether or not this version could be *considered* for
        auto-approval.

        Does not necessarily mean that it would be auto-approved, just that it
        passes the most basic criteria to be considered a candidate by the
        auto_approve command."""
        addon_statuses = [amo.STATUS_PUBLIC]
        if switch_is_active('post-review'):
            # If post-review switch is active, we also accept initial version
            # submissions, so the add-on can also be NOMINATED.
            addon_statuses.append(amo.STATUS_NOMINATED)
        return (
            self.addon.status in addon_statuses and
            self.addon.type in (amo.ADDON_EXTENSION, amo.ADDON_LPAPP) and
            self.is_webextension and
            self.is_unreviewed and
            self.channel == amo.RELEASE_CHANNEL_LISTED)

    @property
    def was_auto_approved(self):
        """Return whether or not this version was auto-approved."""
        from olympia.editors.models import AutoApprovalSummary
        try:
            return self.is_public() and AutoApprovalSummary.objects.filter(
                version=self).get().verdict == amo.AUTO_APPROVED
        except AutoApprovalSummary.DoesNotExist:
            pass
        return False


@use_master
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.addon.reload()
            instance.addon.update_status()
        except models.ObjectDoesNotExist:
            log.info('Got ObjectDoesNotExist processing Version change signal',
                     exc_info=True)
            pass


def inherit_nomination(sender, instance, **kw):
    """
    For new versions pending review, ensure nomination date
    is inherited from last nominated version.
    """
    if kw.get('raw'):
        return
    addon = instance.addon
    if (instance.nomination is None and
            addon.status in amo.UNREVIEWED_ADDON_STATUSES and not
            instance.is_beta):
        instance.inherit_nomination()


def update_incompatible_versions(sender, instance, **kw):
    """
    When a new version is added or deleted, send to task to update if it
    matches any compat overrides.
    """
    try:
        if not instance.addon.type == amo.ADDON_EXTENSION:
            return
    except ObjectDoesNotExist:
        return

    from olympia.addons import tasks
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

    if not kw.get('raw') and (created or instance.deleted):
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
models.signals.post_save.connect(
    update_incompatible_versions, sender=Version,
    dispatch_uid='version_update_incompat')
models.signals.post_save.connect(
    clear_compatversion_cache_on_save, sender=Version,
    dispatch_uid='clear_compatversion_cache_save')

models.signals.pre_delete.connect(
    cleanup_version, sender=Version, dispatch_uid='cleanup_version')
models.signals.post_delete.connect(
    update_status, sender=Version, dispatch_uid='version_update_status')
models.signals.post_delete.connect(
    update_incompatible_versions, sender=Version,
    dispatch_uid='version_update_incompat')
models.signals.post_delete.connect(
    clear_compatversion_cache_on_delete, sender=Version,
    dispatch_uid='clear_compatversion_cache_del')


class LicenseManager(ManagerBase):

    def builtins(self):
        return self.filter(builtin__gt=0).order_by('builtin')


class License(ModelBase):
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
    save_signal, sender=License, dispatch_uid='license_translations')


class ApplicationsVersions(caching.base.CachingMixin, models.Model):

    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              db_column='application_id')
    version = models.ForeignKey(
        Version, related_name='apps', on_delete=models.CASCADE)
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
        if (self.version.is_compatible_by_default and
                self.version.is_compatible_app(amo.APP_IDS[self.application])):
            return ugettext(u'{app} {min} and later').format(
                app=self.get_application_display(),
                min=self.min
            )
        return u'%s %s - %s' % (self.get_application_display(),
                                self.min, self.max)
