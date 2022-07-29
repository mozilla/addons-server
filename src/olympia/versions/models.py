import datetime
import os

from base64 import b64encode
from urllib.parse import urlparse
from fnmatch import fnmatch

import django.dispatch

from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db import models, transaction
from django.db.models import Case, F, Q, When
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.translation import gettext, gettext_lazy as _

import markupsafe
from olympia.constants.applications import APP_IDS
import waffle

from django_statsd.clients import statsd
from publicsuffix2 import get_sld

import olympia.core.logger

from olympia import activity, amo, core
from olympia.amo.decorators import use_primary_db
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import (
    BasePreview,
    LongNameIndex,
    ManagerBase,
    ModelBase,
    OnChangeMixin,
)
from olympia.amo.utils import sorted_groupby, SafeStorage, utc_millesecs_from_epoch
from olympia.applications.models import AppVersion
from olympia.constants.licenses import CC_LICENSES, LICENSES_BY_BUILTIN
from olympia.constants.promoted import PROMOTED_GROUPS_BY_ID
from olympia.constants.scanners import MAD
from olympia.files import utils
from olympia.files.models import File, cleanup_file
from olympia.translations.fields import (
    LinkifiedField,
    PurifiedField,
    TranslatedField,
    save_signal,
)
from olympia.scanners.models import ScannerResult
from olympia.users.models import UserProfile

from .fields import VersionStringField


log = olympia.core.logger.getLogger('z.versions')


# Valid source extensions. Actual validation lives in
# devhub.forms.WithSourceMixin and is slightly more complex (the file
# contents are checked to see if it matches the extension).
# If changing this, make sure devhub.forms.WithSourceMixin.clean_source() and
# source_upload_path() are updated accordingly if needed, and that source
# submission still works both at add-on and version upload time.
VALID_SOURCE_EXTENSIONS = (
    '.zip',
    '.tar.gz',
    '.tgz',
    '.tar.bz2',
)


class VersionManager(ManagerBase):
    def __init__(self, include_deleted=False):
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(deleted=True)
        return qs.select_related('file').transform(Version.transformer)

    def valid(self):
        return self.filter(file__status__in=amo.VALID_FILE_STATUSES)

    def reviewed(self):
        return self.filter(file__status__in=amo.REVIEWED_STATUSES)

    def latest_public_compatible_with(
        self, application, appversions, *, strict_compat_mode=False
    ):
        """Return a queryset filtering the versions so that they are public,
        listed, and compatible with the application and appversions parameters
        passed. The queryset is ordered by creation date descending, allowing
        the caller to get the latest compatible version available.

        `application` is an application id
        `appversions` is a dict containing min and max values, as version ints.

        By default, `appversions['max']` is only considered for versions that
        have strict compatibility enabled, unless the `strict_compat_mode`
        parameter is also True.

        Regardless of whether appversions are passed or not, the queryset will
        be annotated with min_compatible_version and max_compatible_version
        values, corresponding to the min and max application version each
        Version is compatible with.
        """
        filters = {
            'channel': amo.RELEASE_CHANNEL_LISTED,
            'file__status': amo.STATUS_APPROVED,
        }
        filters = {
            'channel': amo.RELEASE_CHANNEL_LISTED,
            'file__status': amo.STATUS_APPROVED,
            'apps__application': application,
        }
        annotations = {
            'min_compatible_version': F('apps__min__version'),
            'max_compatible_version': F('apps__max__version'),
        }
        if 'min' in appversions:
            filters['apps__min__version_int__lte'] = appversions['min']

        if 'max' in appversions:
            if strict_compat_mode:
                filters['apps__max__version_int__gte'] = appversions['max']
            else:
                filters['apps__max__version_int__gte'] = Case(
                    When(file__strict_compatibility=True, then=appversions['max']),
                    default=0,
                )

        # Note: the filter() needs to happen before the annotate(), otherwise
        # it would create extra joins!
        return self.filter(**filters).annotate(**annotations).order_by('-created')

    def auto_approvable(self):
        """Returns a queryset filtered with just the versions that should
        attempted for auto-approval by the cron job."""
        qs = self.filter(file__status=amo.STATUS_AWAITING_REVIEW).filter(
            # For listed, add-on can't be incomplete, deleted or disabled.
            # It also cannot be disabled by user ("invisible"), and can not
            # be a theme either.
            Q(
                channel=amo.RELEASE_CHANNEL_LISTED,
                addon__status__in=(amo.STATUS_NOMINATED, amo.STATUS_APPROVED),
                addon__disabled_by_user=False,
                addon__type__in=(amo.ADDON_EXTENSION, amo.ADDON_LPAPP, amo.ADDON_DICT),
            )
            # For unlisted, add-on can't be deleted or disabled.
            | Q(
                channel=amo.RELEASE_CHANNEL_UNLISTED,
                addon__status__in=(
                    amo.STATUS_NULL,
                    amo.STATUS_NOMINATED,
                    amo.STATUS_APPROVED,
                ),
            )
        )
        return qs


class UnfilteredVersionManagerForRelations(VersionManager):
    """Like VersionManager, but defaults to include deleted objects.

    Designed to be used in reverse relations of Versions like this:
    <Addon>.versions(manager='unfiltered_for_relations').all(), for when you
    want to use the related manager but need to include deleted versions.

    unfiltered_for_relations = UnfilteredVersionManagerForRelations() is
    defined in Version for this to work.
    """

    def __init__(self, include_deleted=True):
        super().__init__(include_deleted=include_deleted)


def source_upload_path(instance, filename):
    # At this point we already know that ext is one of VALID_SOURCE_EXTENSIONS
    # because we already checked for that in
    # /src/olympia/devhub/forms.py#WithSourceMixin.clean_source.
    ext = ''
    for ext in VALID_SOURCE_EXTENSIONS:
        if filename.endswith(ext):
            break

    return os.path.join(
        'version_source',
        utils.id_to_path(instance.pk),
        f'{instance.addon.slug}-{instance.version}-src{ext}',
    )


def source_upload_storage():
    return SafeStorage(user_media='')


class VersionCreateError(ValueError):
    pass


class Version(OnChangeMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(
        'addons.Addon', related_name='versions', on_delete=models.CASCADE
    )
    license = models.ForeignKey(
        'License', null=True, blank=True, on_delete=models.SET_NULL
    )
    release_notes = PurifiedField(db_column='releasenotes', short=False)
    approval_notes = models.TextField(
        db_column='approvalnotes', default='', null=True, blank=True
    )
    version = VersionStringField(max_length=255, default='0.1')

    nomination = models.DateTimeField(null=True)
    reviewed = models.DateTimeField(null=True)

    deleted = models.BooleanField(default=False)

    source = models.FileField(
        upload_to=source_upload_path,
        storage=source_upload_storage,
        null=True,
        blank=True,
        max_length=255,
    )

    channel = models.IntegerField(
        choices=amo.RELEASE_CHANNEL_CHOICES, default=amo.RELEASE_CHANNEL_LISTED
    )

    git_hash = models.CharField(max_length=40, blank=True)

    needs_human_review = models.BooleanField(default=False)

    # The order of those managers is very important: please read the lengthy
    # comment above the Addon managers declaration/instantiation.
    unfiltered = VersionManager(include_deleted=True)
    objects = VersionManager()

    # See UnfilteredVersionManagerForRelations() docstring for usage of this
    # special manager.
    unfiltered_for_relations = UnfilteredVersionManagerForRelations()

    class Meta(ModelBase.Meta):
        db_table = 'versions'
        # This is very important: please read the lengthy comment in Addon.Meta
        # description
        base_manager_name = 'unfiltered'
        ordering = ['-created', '-modified']
        indexes = [
            models.Index(fields=('addon',), name='addon_id'),
            models.Index(fields=('license',), name='license_id'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'version'),
                name='versions_addon_id_version_5a2e75b6_uniq',
            ),
        ]

    def __str__(self):
        return markupsafe.escape(self.version)

    @classmethod
    def from_upload(
        cls,
        upload,
        addon,
        channel,
        *,
        selected_apps=None,
        compatibility=None,
        parsed_data=None,
    ):
        """
        Create a Version instance and corresponding File(s) from a
        FileUpload, an Addon, a channel id and the parsed_data generated by
        parse_addon(). Additionally, for non-themes: either a list of compatible app ids
        needs to be provided as `selected_apps`, or a list of `ApplicationsVersions`
        instances for each compatible app as `compatibility`.

        If `compatibility` is provided: the `version` property of the instances will be
        set to the new upload and the instances saved. If the min and/or max properties
        of the `ApplicationsVersions` instance are none then `AppVersion`s parsed from
        the manifest, or defaults, are used.

        Note that it's the caller's responsability to ensure the file is valid.
        We can't check for that here because an admin may have overridden the
        validation results.
        """
        from olympia.addons.models import AddonReviewerFlags
        from olympia.addons.utils import RestrictionChecker
        from olympia.git.utils import create_git_extraction_entry

        assert parsed_data is not None

        if addon.type == amo.ADDON_STATICTHEME:
            # We don't let developers select apps for static themes
            compatibility = {
                app: (compatibility or {}).get(
                    app, ApplicationsVersions(application=app.id)
                )
                for app in amo.APP_USAGE
            }
        assert selected_apps or compatibility

        if addon.status == amo.STATUS_DISABLED:
            raise VersionCreateError(
                'Addon is Mozilla Disabled; no new versions are allowed.'
            )

        if upload.addon and upload.addon != addon:
            raise VersionCreateError('FileUpload was made for a different Addon')

        if (
            not getattr(upload, 'user', None)
            or not upload.ip_address
            or not upload.source
        ):
            raise VersionCreateError('FileUpload does not have some required fields')

        if not upload.user.last_login_ip or not upload.user.email:
            raise VersionCreateError(
                'FileUpload user does not have some required fields'
            )

        # This should be guaranteed by the linter, just raise an explicit
        # exception if somehow it's wrong.
        if not isinstance(parsed_data.get('install_origins', []), list):
            raise VersionCreateError('install_origins was not validated properly')

        license_id = parsed_data.get('license_id')
        if not license_id and channel == amo.RELEASE_CHANNEL_LISTED:
            previous_version = addon.find_latest_version(channel=channel, exclude=())
            if previous_version and previous_version.license_id:
                license_id = previous_version.license_id
        approval_notes = None
        if parsed_data.get('is_mozilla_signed_extension'):
            approval_notes = (
                'This version has been signed with Mozilla internal certificate.'
            )
        version = cls.objects.create(
            addon=addon,
            approval_notes=approval_notes,
            version=parsed_data['version'],
            license_id=license_id,
            channel=channel,
            release_notes=parsed_data.get('release_notes'),
        )
        with core.override_remote_addr(upload.ip_address):
            # The following log statement is used by foxsec-pipeline.
            # We override the IP because it might be called from a task and we
            # want the original IP from the submitter.
            log.info(
                'New version: %r (%s) from %r',
                version,
                version.pk,
                upload,
                extra={
                    'email': upload.user.email,
                    'guid': addon.guid,
                    'upload': upload.uuid.hex,
                    'user_id': upload.user_id,
                    'from_api': upload.source
                    in (amo.UPLOAD_SOURCE_SIGNING_API, amo.UPLOAD_SOURCE_ADDON_API),
                },
            )
            activity.log_create(amo.LOG.ADD_VERSION, version, addon, user=upload.user)

        if not compatibility:
            compatibility = {
                amo.APP_IDS[app_id]: ApplicationsVersions(application=app_id)
                for app_id in selected_apps
            }

        compatible_apps = {}
        for parsed_app in parsed_data.get('apps', []):
            if parsed_app.appdata not in compatibility:
                # If the user chose to explicitly deselect Firefox for Android
                # we're not creating the respective `ApplicationsVersions`
                # which will have this add-on then be listed only for
                # Firefox specifically.
                continue
            avs = compatibility[parsed_app.appdata]
            avs.version = version
            avs.min = getattr(avs, 'min', parsed_app.min)
            avs.max = getattr(avs, 'max', parsed_app.max)
            avs.save()
            compatible_apps[parsed_app.appdata] = avs

        # Pre-generate compatible_apps property to avoid accidentally
        # triggering queries with that instance later.
        version.compatible_apps = compatible_apps

        # Record declared install origins. base_domain is set automatically.
        if waffle.switch_is_active('record-install-origins'):
            for origin in set(parsed_data.get('install_origins', [])):
                version.installorigin_set.create(origin=origin)

        # Create relevant file.
        File.from_upload(
            upload=upload,
            version=version,
            parsed_data=parsed_data,
        )

        version.inherit_nomination()
        version.disable_old_files()

        # After the upload has been copied to its permanent location, delete it
        # from storage. Keep the FileUpload instance (it gets cleaned up by a
        # cron eventually some time after its creation, in amo.cron.gc()),
        # making sure it's associated with the add-on instance.
        storage.delete(upload.path)
        upload.path = ''
        if upload.addon is None:
            upload.addon = addon
        upload.save()

        version_uploaded.send(instance=version, sender=Version)

        if (
            waffle.switch_is_active('enable-yara')
            or waffle.switch_is_active('enable-customs')
            or waffle.switch_is_active('enable-wat')
        ):
            ScannerResult.objects.filter(upload_id=upload.id).update(version=version)

        if waffle.switch_is_active('enable-uploads-commit-to-git-storage'):
            # Schedule this version for git extraction.
            transaction.on_commit(lambda: create_git_extraction_entry(version=version))

        # Generate a preview and icon for listed static themes
        if (
            addon.type == amo.ADDON_STATICTHEME
            and channel == amo.RELEASE_CHANNEL_LISTED
        ):
            theme_data = parsed_data.get('theme', {})
            generate_static_theme_preview(theme_data, version.pk)

        # Reset add-on reviewer flags to disable auto-approval and require
        # admin code review if the package has already been signed by mozilla.
        reviewer_flags_defaults = {}
        is_mozilla_signed = parsed_data.get('is_mozilla_signed_extension')
        if upload.validation_timeout:
            reviewer_flags_defaults['needs_admin_code_review'] = True
        if is_mozilla_signed and addon.type != amo.ADDON_LPAPP:
            reviewer_flags_defaults['needs_admin_code_review'] = True
            reviewer_flags_defaults['auto_approval_disabled'] = True

        # Check if the approval should be restricted
        if not RestrictionChecker(upload=upload).is_auto_approval_allowed():
            flag = (
                'auto_approval_disabled'
                if channel == amo.RELEASE_CHANNEL_LISTED
                else 'auto_approval_disabled_unlisted'
            )
            reviewer_flags_defaults[flag] = True

        if reviewer_flags_defaults:
            AddonReviewerFlags.objects.update_or_create(
                addon=addon, defaults=reviewer_flags_defaults
            )

        # Authors need to be notified about auto-approval delay again since
        # they are submitting a new version.
        addon.reset_notified_about_auto_approval_delay()

        # Track the time it took from first upload through validation
        # (and whatever else) until a version was created.
        upload_start = utc_millesecs_from_epoch(upload.created)
        now = datetime.datetime.now()
        now_ts = utc_millesecs_from_epoch(now)
        upload_time = now_ts - upload_start

        log.info(
            'Time for version {version} creation from upload: {delta}; '
            'created={created}; now={now}'.format(
                delta=upload_time, version=version, created=upload.created, now=now
            )
        )
        statsd.timing('devhub.version_created_from_upload', upload_time)

        return version

    def license_url(self, impala=False):
        return reverse('addons.license', args=[self.addon.slug, self.version])

    def get_url_path(self):
        if self.channel == amo.RELEASE_CHANNEL_UNLISTED:
            return ''
        return reverse('addons.versions', args=[self.addon.slug])

    def delete(self, hard=False):
        # To avoid a circular import
        from .tasks import delete_preview_files

        log.info('Version deleted: %r (%s)', self, self.id)
        activity.log_create(amo.LOG.DELETE_VERSION, self.addon, str(self.version))

        if hard:
            super().delete()
        else:
            # By default we soft delete so we can keep the files for comparison
            # and a record of the version number.
            if hasattr(self, 'file'):
                # .file should always exist but we don't want to break delete regardless
                self.file.update(status=amo.STATUS_DISABLED)
            self.deleted = True
            self.save()

            # Clear pending rejection flag (we have the activity log for
            # records purposes, the flag serves no purpose anymore if the
            # version is deleted).
            VersionReviewerFlags.objects.filter(version=self).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )

            previews_pks = list(
                VersionPreview.objects.filter(version__id=self.id).values_list(
                    'id', flat=True
                )
            )

            for preview_pk in previews_pks:
                delete_preview_files.delay(preview_pk)

    @property
    def is_user_disabled(self):
        return (
            self.file.status == amo.STATUS_DISABLED
            and self.file.original_status != amo.STATUS_NULL
        )

    @is_user_disabled.setter
    def is_user_disabled(self, disable):
        # User wants to disable (and the File isn't already).
        if disable:
            activity.log_create(amo.LOG.DISABLE_VERSION, self.addon, self)
            if (file_ := self.file) and file_.status != amo.STATUS_DISABLED:
                file_.update(original_status=file_.status, status=amo.STATUS_DISABLED)
        # User wants to re-enable (and user did the disable, not Mozilla).
        else:
            activity.log_create(amo.LOG.ENABLE_VERSION, self.addon, self)
            if (file_ := self.file) and file_.original_status != amo.STATUS_NULL:
                file_.update(
                    status=file_.original_status, original_status=amo.STATUS_NULL
                )

    @cached_property
    def all_activity(self):
        # prefetch_related() and not select_related() the ActivityLog to make
        # sure its transformer is called.
        return self.versionlog_set.prefetch_related('activity_log').order_by('created')

    def _create_compatible_apps(self, avs):
        apps = {}
        for av in avs:
            av.version = self
            app_id = av.application
            if app_id in amo.APP_IDS:
                apps[amo.APP_IDS[app_id]] = av
        return apps

    @property
    def compatible_apps(self):
        """Returns a mapping of {APP: ApplicationsVersions}.  This may have been filled
        by the transformer already."""
        if not hasattr(self, '_compatible_apps'):
            # Calculate from the related compat instances.
            self._compatible_apps = self._create_compatible_apps(
                self.apps.all().select_related('min', 'max')
            )
        return self._compatible_apps

    @compatible_apps.setter
    def compatible_apps(self, value):
        self._compatible_apps = value

    def set_compatible_apps(self, apps):
        from olympia.addons.tasks import index_addons  # circular import

        # We shouldn't be trying to set compatiblity on addons don't allow it.
        if self.addon and not self.addon.can_set_compatibility:
            return

        # clear any removed applications
        self.apps.exclude(application__in=(app.id for app in apps)).delete()
        # then save the instances
        for applications_versions in apps.values():
            if not applications_versions.id:
                # set version if we have it, for new instances
                applications_versions.version = self
            applications_versions.save()
        # Update cache on the model.
        self.compatible_apps = apps
        # Make sure the add-on is properly re-indexed
        index_addons.delay([self.addon.id])

    @cached_property
    def is_compatible_by_default(self):
        """Returns whether or not the add-on is considered compatible by
        default."""
        return not self.file.strict_compatibility

    def is_public(self):
        # To be public, a version must not be deleted, must belong to a public
        # addon, and its attached file must have a public status.
        try:
            return (
                not self.deleted
                and self.addon.is_public()
                and self.file.status == amo.STATUS_APPROVED
            )
        except ObjectDoesNotExist:
            return False

    @property
    def is_mozilla_signed(self):
        """Is the file a special "Mozilla Signed Extension"

        See https://wiki.mozilla.org/Add-ons/InternalSigning for more details.
        We use that information to workaround compatibility limits for legacy
        add-ons and to avoid them receiving negative boosts compared to
        WebExtensions.

        See https://github.com/mozilla/addons-server/issues/6424
        """
        return self.file.is_mozilla_signed_extension

    @property
    def is_unreviewed(self):
        return self.file.status in amo.UNREVIEWED_FILE_STATUSES

    @property
    def sources_provided(self):
        return bool(self.source)

    @classmethod
    def transformer(cls, versions):
        """Attach all the compatible apps and the file to the versions."""
        if not versions:
            return

        ids = {v.id for v in versions}
        avs = ApplicationsVersions.objects.filter(version__in=ids).select_related(
            'min', 'max'
        )

        def rollup(xs):
            groups = sorted_groupby(xs, 'version_id')
            return {k: list(vs) for k, vs in groups}

        av_dict = rollup(avs)

        for version in versions:
            version.compatible_apps = version._create_compatible_apps(
                av_dict.get(version.id, [])
            )

    @classmethod
    def transformer_promoted(cls, versions):
        """Attach the promoted approvals to the versions."""
        if not versions:
            return

        PromotedApproval = versions[0].promoted_approvals.model

        ids = {v.id for v in versions}

        approvals = list(
            PromotedApproval.objects.filter(version_id__in=ids).values_list(
                'version_id', 'group_id', 'application_id', named=True
            )
        )

        approval_dict = {
            version_id: list(groups)
            for version_id, groups in sorted_groupby(approvals, 'version_id')
        }
        for version in versions:
            v_id = version.id
            groups = [
                (
                    PROMOTED_GROUPS_BY_ID.get(approval.group_id),
                    APP_IDS.get(approval.application_id),
                )
                for approval in approval_dict.get(v_id, [])
                if approval.group_id in PROMOTED_GROUPS_BY_ID
            ]
            version.approved_for_groups = groups

    @classmethod
    def transformer_activity(cls, versions):
        """Attach all the activity to the versions."""
        from olympia.activity.models import VersionLog

        ids = {v.id for v in versions}
        if not versions:
            return

        # Ideally, we'd start from the ActivityLog, but because VersionLog
        # to ActivityLog isn't a OneToOneField, we wouldn't be able to find
        # the version easily afterwards - we can't even do a
        # select_related('versionlog') and try to traverse the relation to find
        # the version. So, instead, start from VersionLog, but make sure to use
        # prefetch_related() (and not select_related() - yes, it's one extra
        # query, but it's worth it to benefit from the default transformer) so
        # that the ActivityLog default transformer is called.
        al = (
            VersionLog.objects.prefetch_related('activity_log')
            .filter(version__in=ids)
            .order_by('created')
        )

        def rollup(xs):
            groups = sorted_groupby(xs, 'version_id')
            return {k: list(vs) for k, vs in groups}

        al_dict = rollup(al)

        for version in versions:
            v_id = version.id
            version.all_activity = al_dict.get(v_id, [])

    @classmethod
    def transformer_license(cls, versions):
        """Attach all the licenses to the versions.

        Do not use if you need the license text: it's explicitly deferred in
        this transformer, because it should only be used when listing multiple
        versions, where returning license text is not supposed to be needed.

        The translations app doesn't fully handle evaluating a deferred field,
        so the callers need to make sure the license text will never be needed
        on instances returned by a queryset transformed by this method."""
        if not versions:
            return
        license_ids = {ver.license_id for ver in versions}
        licenses = License.objects.filter(id__in=license_ids).defer('text')
        license_dict = {lic.id: lic for lic in licenses}

        for version in versions:
            license = license_dict.get(version.license_id)
            if license:
                version.license = license

    @classmethod
    def transformer_auto_approvable(cls, versions):
        """Attach  auto-approvability information to the versions."""
        ids = {v.id for v in versions}
        if not ids:
            return

        auto_approvable = (
            Version.objects.auto_approvable()
            .filter(pk__in=ids)
            .values_list('pk', flat=True)
        )

        for version in versions:
            version.is_ready_for_auto_approval = version.pk in auto_approvable

    def disable_old_files(self):
        """
        Disable files from versions older than the current one in the same
        channel and awaiting review. Used when uploading a new version.

        Does nothing if the current instance is unlisted.
        """
        if self.channel == amo.RELEASE_CHANNEL_LISTED:
            qs = File.objects.filter(
                version__addon=self.addon_id,
                version__lt=self.id,
                version__deleted=False,
                version__channel=self.channel,
                status=amo.STATUS_AWAITING_REVIEW,
            )
            # Use File.update so signals are triggered.
            for f in qs:
                f.update(status=amo.STATUS_DISABLED)

    def reset_nomination_time(self, nomination=None):
        if not self.nomination or nomination:
            nomination = nomination or datetime.datetime.now()
            # We need signal=False not to call update_status (which calls us).
            self.update(nomination=nomination, _signal=False)

    def inherit_nomination(self):
        qs = (
            Version.objects.filter(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
            .exclude(nomination=None)
            .exclude(id=self.pk)
            .filter(file__status=amo.STATUS_AWAITING_REVIEW)
            .exclude(reviewerflags__pending_rejection__isnull=False)
            .values_list('nomination', flat=True)
            .order_by('-nomination')
        )
        # If no matching version is found, we end up passing nomination=None
        # which will update the nomination to datetime.now() if it wasn't
        # already set on the instance.
        self.reset_nomination_time(nomination=qs.first())

    @cached_property
    def is_ready_for_auto_approval(self):
        """Return whether or not this version could be *considered* for
        auto-approval.

        Does not necessarily mean that it would be auto-approved, just that it
        passes the most basic criteria to be considered a candidate by the
        auto_approve command."""
        return Version.objects.auto_approvable().filter(id=self.id).exists()

    @property
    def was_auto_approved(self):
        """Return whether or not this version was auto-approved."""
        from olympia.reviewers.models import AutoApprovalSummary

        try:
            return (
                self.is_public()
                and AutoApprovalSummary.objects.filter(version=self).get().verdict
                == amo.AUTO_APPROVED
            )
        except AutoApprovalSummary.DoesNotExist:
            pass
        return False

    @property
    def has_been_human_reviewed(self):
        """Return whether or not this version was reviewed by a human."""
        from olympia.reviewers.models import AutoApprovalSummary

        autoapproval = AutoApprovalSummary.objects.filter(version=self).first()

        return (
            self.file.status == amo.STATUS_APPROVED
            and (
                not autoapproval
                or autoapproval.verdict == amo.NOT_AUTO_APPROVED
                or autoapproval.confirmed is True
            )
        ) or (self.file.status == amo.STATUS_DISABLED and self.file.reviewed)

    def get_background_images_encoded(self, header_only=False):
        file_obj = self.file
        return {
            name: force_str(b64encode(background))
            for name, background in utils.get_background_images(
                file_obj, theme_data=None, header_only=header_only
            ).items()
        }

    def can_be_disabled_and_deleted(self):
        # see https://github.com/mozilla/addons-server/issues/15121#issuecomment-667226959  # noqa
        # "It should apply to the <groups> that require a review to be badged"
        from olympia.promoted.models import PromotedApproval

        if self != self.addon.current_version or (
            not (group := self.addon.promoted_group())
            or not (group.badged and group.pre_review)
        ):
            return True

        # We're trying to check if the current version of a promoted add-on can
        # be disabled/deleted. We'll allow if if the previous valid version
        # already had the promotion approval, so that we don't end up with a
        # promoted add-on w/ a current version that hasn't had a manual review.
        previous_version = (
            self.addon.versions.valid()
            .filter(channel=self.channel)
            .exclude(id=self.id)
            .no_transforms()
            # .distinct() forces a nested subquery making the whole thing
            # possible in a single query
            .distinct()[:1]
        )
        previous_approval = PromotedApproval.objects.filter(
            group_id=group.id, version__in=previous_version
        )
        return previous_approval.exists()

    @property
    def is_blocked(self):
        block = self.addon.block
        return bool(block and block.is_version_blocked(self.version))

    @property
    def pending_rejection(self):
        try:
            return self.reviewerflags.pending_rejection
        except VersionReviewerFlags.DoesNotExist:
            return None

    @property
    def pending_rejection_by(self):
        try:
            return self.reviewerflags.pending_rejection_by
        except VersionReviewerFlags.DoesNotExist:
            return None

    @property
    def needs_human_review_by_mad(self):
        try:
            return self.reviewerflags.needs_human_review_by_mad
        except VersionReviewerFlags.DoesNotExist:
            return False

    @property
    def maliciousness_score(self):
        try:
            # We use the score of the MAD scanner because it is the 'ensemble'
            # score (i.e. score computed using all other scanner scores).
            # We iterate on all .scannerresults instead of doing .filter()
            # because there shouldn't be many results, and chances are the
            # caller (normally reviewer tools review page) will have prefetched
            # all scanner results.
            score = [
                result.score
                for result in self.scannerresults.all()
                if result.scanner == MAD
            ][0]
        except IndexError:
            score = None
        return float(score * 100) if score and score > 0 else 0

    @cached_property
    def approved_for_groups(self):
        approvals = list(self.promoted_approvals.all())
        return [
            (PROMOTED_GROUPS_BY_ID.get(approval.group_id), approval.application)
            for approval in approvals
            if approval.group_id in PROMOTED_GROUPS_BY_ID
        ]

    def get_review_status_for_auto_approval_and_delay_reject(self):
        status = None
        if (reviewer_flags := getattr(self, 'reviewerflags', None)) and (
            rejection_date := reviewer_flags.pending_rejection
        ):
            status = gettext('Delay-rejected, scheduled for %s') % rejection_date.date()
        elif self.file.status == amo.STATUS_APPROVED:
            summary = getattr(self, 'autoapprovalsummary', None)
            if summary and summary.verdict == amo.AUTO_APPROVED:
                status = (
                    gettext('Auto-approved, Confirmed')
                    if summary.confirmed is True
                    else gettext('Auto-approved, not Confirmed')
                )
            else:
                status = gettext('Approved, Manual')
        return status

    def get_review_status_display(self, show_auto_approval_and_delay_reject=False):
        if self.deleted:
            return gettext('Deleted')
        if self.is_user_disabled:
            return gettext('Disabled by Developer')

        # This is the default status
        status = self.file.get_review_status_display()
        # But optionally, we override with more a specific status if available
        return (
            show_auto_approval_and_delay_reject
            and self.get_review_status_for_auto_approval_and_delay_reject()
            or status
        )


class VersionReviewerFlags(ModelBase):
    version = models.OneToOneField(
        Version,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name='reviewerflags',
    )
    needs_human_review_by_mad = models.BooleanField(default=False, db_index=True)
    pending_rejection = models.DateTimeField(
        default=None, null=True, blank=True, db_index=True
    )
    pending_rejection_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.CASCADE
    )
    pending_content_rejection = models.BooleanField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name='pending_rejection_all_none',
                check=(
                    models.Q(
                        pending_rejection__isnull=True,
                        pending_rejection_by__isnull=True,
                        pending_content_rejection__isnull=True,
                    )
                    | models.Q(
                        pending_rejection__isnull=False,
                        pending_rejection_by__isnull=False,
                        pending_content_rejection__isnull=False,
                    )
                ),
            ),
        ]


def version_review_flags_save_signal(sender, instance, **kw):
    if not instance.pending_rejection:
        instance.pending_rejection_by = None


models.signals.pre_save.connect(
    version_review_flags_save_signal,
    sender=VersionReviewerFlags,
    dispatch_uid='version_review_flags',
)


def generate_static_theme_preview(theme_data, version_pk):
    """This redirection is so we can mock generate_static_theme_preview, where
    needed, in tests."""
    # To avoid a circular import
    from . import tasks

    tasks.generate_static_theme_preview.delay(theme_data, version_pk)


class VersionPreview(BasePreview, ModelBase):
    version = models.ForeignKey(
        Version, related_name='previews', on_delete=models.CASCADE
    )
    position = models.IntegerField(default=0)
    sizes = models.JSONField(default=dict)
    colors = models.JSONField(default=None, null=True)
    media_folder = 'version-previews'

    class Meta:
        db_table = 'version_previews'
        ordering = ('position', 'created')
        indexes = [
            LongNameIndex(
                fields=('version',), name='version_previews_version_id_fk_versions_id'
            ),
            models.Index(
                fields=('version', 'position', 'created'),
                name='version_position_created_idx',
            ),
        ]

    @cached_property
    def caption(self):
        """We only don't support defining a caption for previews because
        they're auto-generated.  This is for compatibility with Addon Preview
        objects. (it's a cached_property so it can be set transparently)"""
        return None


models.signals.post_delete.connect(
    VersionPreview.delete_preview_files,
    sender=VersionPreview,
    dispatch_uid='delete_preview_files',
)


@use_primary_db
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.addon.reload()
            instance.addon.update_status()
        except models.ObjectDoesNotExist:
            log.info(
                'Got ObjectDoesNotExist processing Version change signal', exc_info=True
            )
            pass


def inherit_nomination(sender, instance, **kw):
    """
    For new versions pending review, ensure nomination date
    is inherited from last nominated version.
    """
    if kw.get('raw'):
        return
    addon = instance.addon
    if instance.nomination is None and addon.status == amo.STATUS_NOMINATED:
        instance.inherit_nomination()


def cleanup_version(sender, instance, **kw):
    """On delete of the version object call the file delete and signals."""
    if kw.get('raw'):
        return
    if hasattr(instance, 'file'):
        cleanup_file(instance.file.__class__, instance.file)


version_uploaded = django.dispatch.Signal()
models.signals.pre_save.connect(
    save_signal, sender=Version, dispatch_uid='version_translations'
)
models.signals.post_save.connect(
    update_status, sender=Version, dispatch_uid='version_update_status'
)
models.signals.post_save.connect(
    inherit_nomination, sender=Version, dispatch_uid='version_inherit_nomination'
)
models.signals.pre_delete.connect(
    cleanup_version, sender=Version, dispatch_uid='cleanup_version'
)
models.signals.post_delete.connect(
    update_status, sender=Version, dispatch_uid='version_update_status'
)


class LicenseManager(ManagerBase):
    def builtins(self, cc=False):
        cc_filter = Q(builtin__in=CC_LICENSES.keys())
        if not cc:
            cc_filter = ~cc_filter
        return self.filter(cc_filter, builtin__gt=0).order_by('builtin')


class License(ModelBase):
    OTHER = 0

    id = PositiveAutoField(primary_key=True)
    name = TranslatedField()
    url = models.URLField(null=True)
    builtin = models.PositiveIntegerField(default=OTHER)
    text = LinkifiedField()
    on_form = models.BooleanField(
        default=False, help_text='Is this a license choice in the devhub?'
    )

    objects = LicenseManager()

    class Meta:
        db_table = 'licenses'
        indexes = [models.Index(fields=('builtin',), name='builtin_idx')]

    def __str__(self):
        license = self._constant or self
        return str(license.name)

    @property
    def _constant(self):
        return LICENSES_BY_BUILTIN.get(self.builtin)

    @property
    def creative_commons(self):
        return bool((constant := self._constant) and constant.creative_commons)

    @property
    def icons(self):
        return ((constant := self._constant) and constant.icons) or ''

    @property
    def slug(self):
        return ((constant := self._constant) and constant.slug) or None


models.signals.pre_save.connect(
    save_signal, sender=License, dispatch_uid='license_translations'
)


class ApplicationsVersions(models.Model):
    id = PositiveAutoField(primary_key=True)
    application = models.PositiveIntegerField(
        choices=amo.APPS_CHOICES, db_column='application_id'
    )
    version = models.ForeignKey(Version, related_name='apps', on_delete=models.CASCADE)
    min = models.ForeignKey(
        AppVersion, db_column='min', related_name='min_set', on_delete=models.CASCADE
    )
    max = models.ForeignKey(
        AppVersion, db_column='max', related_name='max_set', on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'applications_versions'
        constraints = [
            models.UniqueConstraint(
                fields=('application', 'version'), name='application_id'
            ),
        ]

    def get_application_display(self):
        return str(amo.APPS_ALL[self.application].pretty)

    def get_latest_application_version(self):
        return (
            AppVersion.objects.filter(
                ~models.Q(version__contains='*'), application=self.application
            )
            .order_by('-version_int')
            .first()
        )

    def __str__(self):
        try:
            if self.version.is_compatible_by_default:
                return gettext('{app} {min} and later').format(
                    app=self.get_application_display(), min=self.min
                )
            return f'{self.get_application_display()} {self.min} - {self.max}'
        except ObjectDoesNotExist:
            return self.get_application_display()


class InstallOrigin(ModelBase):
    version = models.ForeignKey(Version, on_delete=models.CASCADE)
    origin = models.CharField(max_length=255)
    base_domain = models.CharField(max_length=255)

    @staticmethod
    def punycode(hostname):
        return hostname.encode('idna').decode('utf-8').lower()

    def _extract_base_domain_from_origin(self, origin):
        """Extract base domain from an origin according to publicsuffix list.
        Handles IDNs in both unicode and punycode form, but always return the
        base domain in punycode."""
        hostname = urlparse(origin).hostname or ''
        # If the domain is an Internationalized Domain Name (IDN), we want to
        # return the punycode version. This follows publicsuffix2's default
        # behavior - idna=True is the default and that means it expects input
        # to be idna-encoded. That's the format we'd like to return anyway, to
        # make it obvious to reviewers/admins when the base domain is an IDN.
        hostname = self.punycode(hostname)
        return get_sld(hostname)

    def save(self, *args, **kwargs):
        self.base_domain = self._extract_base_domain_from_origin(self.origin)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.version.version} : {self.origin} ({self.base_domain})'


class DeniedInstallOrigin(ModelBase):
    ERROR_MESSAGE = _('The install origin {origin} is not permitted.')

    hostname_pattern = models.CharField(
        max_length=255,
        unique=True,
        help_text='Hostname unix-style pattern to deny.',
    )
    include_subdomains = models.BooleanField(
        default=False,
        help_text=(
            'Automatically check for subdomains of hostname pattern '
            '(Additional check with `*.` prepended to the original pattern).'
        ),
    )

    def save(self, *args, **kwargs):
        # Transform pattern so that we always compare things in punycode.
        self.hostname_pattern = InstallOrigin.punycode(self.hostname_pattern)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.hostname_pattern

    @classmethod
    def find_denied_origins(cls, install_origins):
        """
        Filter input list of origins to only return denied origins (Empty set
        returned means all the install origins passed in argument are allowed).
        """
        denied = set()
        denied_install_origins = cls.objects.all()
        for origin in install_origins:
            hostname = InstallOrigin.punycode(urlparse(origin).hostname or '')
            for denied_origin in denied_install_origins:
                if fnmatch(hostname, denied_origin.hostname_pattern) or (
                    denied_origin.include_subdomains
                    and fnmatch(hostname, f'*.{denied_origin.hostname_pattern}')
                ):
                    denied.add(origin)
        return denied
