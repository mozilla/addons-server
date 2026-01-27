import functools
import operator
import os
import re
from base64 import b64encode
from datetime import datetime, timedelta
from fnmatch import fnmatch
from urllib.parse import urlparse

import django.dispatch
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db import models
from django.db.models import Case, F, Q, When
from django.dispatch import receiver
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.translation import gettext, gettext_lazy as _

import markupsafe
import waffle
from django_statsd.clients import statsd
from publicsuffix2 import get_sld

import olympia.core.logger
from olympia import activity, amo, core
from olympia.amo.decorators import use_primary_db
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import (
    BasePreview,
    BaseQuerySet,
    LongNameIndex,
    ManagerBase,
    ModelBase,
    OnChangeMixin,
)
from olympia.amo.utils import (
    SafeStorage,
    id_to_path,
    sorted_groupby,
    utc_millesecs_from_epoch,
)
from olympia.applications.models import AppVersion
from olympia.constants.applications import APP_IDS
from olympia.constants.licenses import CC_LICENSES, FORM_LICENSES, LICENSES_BY_BUILTIN
from olympia.files import utils
from olympia.files.models import File, cleanup_file
from olympia.scanners.models import ScannerResult
from olympia.translations.fields import (
    LinkifiedField,
    PurifiedMarkdownField,
    TranslatedField,
    save_signal,
)
from olympia.users.models import UserProfile
from olympia.users.utils import RestrictionChecker, get_task_user
from olympia.versions.compare import version_int
from olympia.zadmin.models import get_config

from .fields import VersionStringField
from .utils import get_review_due_date


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


class VersionQuerySet(BaseQuerySet):
    def not_rejected(self):
        return self.exclude(
            file__status=amo.STATUS_DISABLED,
            file__status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
        )


class VersionManager(ManagerBase):
    _queryset_class = VersionQuerySet

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

    def approved(self):
        return self.filter(file__status__in=amo.APPROVED_STATUSES)

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
            'channel': amo.CHANNEL_LISTED,
            'file__status': amo.STATUS_APPROVED,
        }
        filters = {
            'channel': amo.CHANNEL_LISTED,
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
                channel=amo.CHANNEL_LISTED,
                addon__status__in=amo.VALID_ADDON_STATUSES,
                addon__disabled_by_user=False,
                addon__type__in=(amo.ADDON_EXTENSION, amo.ADDON_LPAPP, amo.ADDON_DICT),
            )
            # For unlisted, add-on can't be deleted or disabled.
            | Q(
                channel=amo.CHANNEL_UNLISTED,
                addon__status__in=amo.VALID_ADDON_STATUSES + (amo.STATUS_NULL,),
            )
        )
        return qs

    def should_have_due_date(self, negate=False):
        """Returns a queryset filtered to versions that should have a due date set.
        If `negate=True` the queryset will contain versions that should not have a
        due date instead."""
        method = getattr(self, 'exclude' if negate else 'filter')
        return (
            method(
                functools.reduce(
                    operator.or_, self.get_due_date_reason_q_objects().values()
                )
            )
            .using('default')
            .distinct()
        )

    @classmethod
    def get_due_date_reason_q_objects(cls):
        """Class method that returns a dict with all the Q objects needed to determine
        if a version should_have_due_date is true as values, and the annotation names
        for each reason as values."""
        from olympia.reviewers.models import NeedsHumanReview

        reasons = {}

        # Versions of themes not yet reviewed should have a due date.
        reasons['is_from_theme_awaiting_review'] = (
            Q(
                Q(
                    channel=amo.CHANNEL_LISTED,
                    addon__status__in=amo.VALID_ADDON_STATUSES,
                )
                | Q(channel=amo.CHANNEL_UNLISTED)
            )
            & Q(
                file__status=amo.STATUS_AWAITING_REVIEW,
                reviewerflags__pending_rejection__isnull=True,
                addon__type=amo.ADDON_STATICTHEME,
            )
            & ~Q(addon__status=amo.STATUS_DELETED)
        )

        # Abuse-related reasons & developer replies always trigger a due
        # date even if the version has been disabled / not signed.
        abuse_related_or_developer_reply = list(
            NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED
        ) + [NeedsHumanReview.REASONS.DEVELOPER_REPLY]
        for entry in abuse_related_or_developer_reply:
            reasons[entry.annotation] = Q(
                needshumanreview__is_active=True,
                needshumanreview__reason=entry.value,
            )

        # Versions that haven't been disabled or have ever been signed and have
        # the explicit needs human review flag should have a due date (it gets
        # dropped on various reviewer actions).
        is_other_needs_human_review = Q(
            ~Q(file__status=amo.STATUS_DISABLED) | Q(file__is_signed=True),
            needshumanreview__is_active=True,
        )
        for entry in set(NeedsHumanReview.REASONS).difference(
            abuse_related_or_developer_reply
        ):
            reasons[entry.annotation] = Q(
                is_other_needs_human_review,
                needshumanreview__reason=entry.value,
            )
        return reasons


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
        id_to_path(instance.pk),
        f'{instance.addon.slug}-{instance.version}-src{ext}',
    )


def source_upload_storage():
    return SafeStorage(root_setting='MEDIA_ROOT')


class VersionCreateError(ValueError):
    pass


class Version(OnChangeMixin, ModelBase):
    """
    A version is a unique iteration of an add-on.
    Versions are created for a specific channel and
    relate to a specific uploaded XPI file.
    """

    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(
        'addons.Addon', related_name='versions', on_delete=models.CASCADE
    )
    license = models.ForeignKey(
        'License', null=True, blank=True, on_delete=models.SET_NULL
    )
    release_notes = PurifiedMarkdownField(
        db_column='releasenotes', short=False, max_length=3000
    )
    # Note that max_length isn't enforced at the database level for TextFields,
    # but the API serializer & form are set to obey it.
    approval_notes = models.TextField(
        db_column='approvalnotes', default='', blank=True, max_length=3000
    )
    version = VersionStringField(max_length=255, default='0.1')

    due_date = models.DateTimeField(null=True, blank=True)
    human_review_date = models.DateTimeField(null=True)

    deleted = models.BooleanField(default=False)

    source = models.FileField(
        upload_to=source_upload_path,
        storage=source_upload_storage,
        null=True,
        blank=True,
        max_length=255,
    )

    channel = models.IntegerField(
        choices=amo.CHANNEL_CHOICES.items(), default=amo.CHANNEL_LISTED
    )

    git_hash = models.CharField(max_length=40, blank=True)

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
            models.Index(fields=('due_date',), name='versions_due_date_b9c73ed7'),
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
        client_info=None,
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
        from olympia.devhub.tasks import send_initial_submission_acknowledgement_email
        from olympia.reviewers.models import NeedsHumanReview

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
        if not license_id and channel == amo.CHANNEL_LISTED:
            previous_version = addon.find_latest_version(channel=channel, exclude=())
            if previous_version and previous_version.license_id:
                license_id = previous_version.license_id
        approval_notes = parsed_data.get('approval_notes', '')
        if parsed_data.get('is_mozilla_signed_extension'):
            approval_notes = (
                'This version has been signed with Mozilla internal certificate.'
            )

        previous_version_had_needs_human_review = (
            addon.versions_triggering_needs_human_review_inheritance(channel).exists()
        )

        version = cls.objects.create(
            addon=addon,
            approval_notes=approval_notes,
            version=parsed_data['version'],
            license_id=license_id,
            channel=channel,
            release_notes=parsed_data.get('release_notes'),
        )
        with core.override_remote_addr_or_metadata(
            ip_address=upload.ip_address, metadata=upload.request_metadata
        ):
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
            if previous_version_had_needs_human_review:
                NeedsHumanReview(
                    version=version, reason=NeedsHumanReview.REASONS.INHERITANCE
                ).save(_user=get_task_user())

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

        version.reset_due_date()
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

        if not compatibility:
            compatibility = {
                amo.APP_IDS[app_id]: ApplicationsVersions(application=app_id)
                for app_id in selected_apps
            }

        compatible_apps = {}
        for avs_from_parsed_data in parsed_data.get('apps', []):
            application = APP_IDS.get(avs_from_parsed_data.application)
            if avs_from_parsed_data.locked_from_manifest:
                # In that case, the manifest takes precedence.
                avs = avs_from_parsed_data
            elif application not in compatibility:
                # In that case, the developer didn't include compatibility
                # information we have to follow, and they didn't select this
                # app at upload time, so we ignore that app.
                continue
            else:
                # They selected the app we're currently dealing with, so let's
                # try to build some compatibility info from what we have.
                avs = compatibility[application]
                # Start by considering the data is coming from the manifest,
                # but override if min or max were provided.
                avs.originated_from = avs_from_parsed_data.originated_from
                if avs.min_id is None:
                    avs.min = avs_from_parsed_data.min
                    avs.originated_from = amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER
                if avs.max_id is None:
                    avs.max = avs_from_parsed_data.max
                    avs.originated_from = amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER
            avs.pk = None  # Make sure to create new ApplicationsVersions in any case.
            avs.version = version
            avs.save()
            compatible_apps[application] = avs

        # Pre-generate compatible_apps property to avoid accidentally
        # triggering queries with that instance later.
        version.compatible_apps = compatible_apps

        version_uploaded.send(instance=version, sender=Version)

        ScannerResult.objects.filter(upload_id=upload.id).update(version=version)

        # Generate a preview and icon for listed static themes
        if addon.type == amo.ADDON_STATICTHEME and channel == amo.CHANNEL_LISTED:
            theme_data = parsed_data.get('theme', {})
            generate_static_theme_preview(theme_data, version.pk)

        # Reset add-on reviewer flags to disable auto-approval and require
        # admin code review if the package has already been signed by mozilla.
        reviewer_flags_defaults = {}
        is_mozilla_signed = parsed_data.get('is_mozilla_signed_extension')
        if is_mozilla_signed and addon.type != amo.ADDON_LPAPP:
            reviewer_flags_defaults['auto_approval_disabled'] = True

        # Check if the approval should be restricted
        if not RestrictionChecker(upload=upload).is_auto_approval_allowed():
            flag = (
                'auto_approval_disabled'
                if channel == amo.CHANNEL_LISTED
                else 'auto_approval_disabled_unlisted'
            )
            reviewer_flags_defaults[flag] = True
            activity.log_create(
                amo.LOG.DISABLE_AUTO_APPROVAL,
                addon,
                details={
                    'channel': version.channel,
                    'comments': (
                        f'{version.get_channel_display()} auto-approval automatically '
                        'disabled because of a restriction'
                    ),
                },
                user=get_task_user(),
            )

        if reviewer_flags_defaults:
            AddonReviewerFlags.objects.update_or_create(
                addon=addon, defaults=reviewer_flags_defaults
            )

        # First submission of every add-on should trigger an initial
        # submission acknowledgement email regardless of channel.
        if (
            not addon.versions(manager='unfiltered_for_relations')
            .exclude(pk=version.pk)
            .exists()
        ):
            send_initial_submission_acknowledgement_email.delay(
                addon.pk, version.channel, upload.user.email
            )

        # Unlisted versions approval is delayed depending on how far we are
        # from creation of the add-on. This is applied only once, during the
        # first unlisted version creation of an extension (so the flag can be
        # dropped by admins or reviewers, not affecting subsequent versions).
        if (
            channel == amo.CHANNEL_UNLISTED
            and addon.type == amo.ADDON_EXTENSION
            and not addon.versions(manager='unfiltered_for_relations')
            .filter(channel=amo.CHANNEL_UNLISTED)
            .exclude(pk=version.pk)
            .exists()
        ):
            initial_delay = get_config(amo.config_keys.INITIAL_DELAY_FOR_UNLISTED)
            auto_approval_delay_for_unlisted = addon.created + timedelta(
                seconds=initial_delay
            )
            if datetime.now() < auto_approval_delay_for_unlisted:
                addon.set_auto_approval_delay_if_higher_than_existing(
                    auto_approval_delay_for_unlisted, unlisted_only=True
                )

        # Reload the flags for the add-on in case some code is using it after
        # creating the version - the related field could be out of date.
        try:
            version.addon.reviewerflags.reload()
        except AddonReviewerFlags.DoesNotExist:
            pass

        # Track the time it took from first upload through validation
        # (and whatever else) until a version was created.
        upload_start = utc_millesecs_from_epoch(upload.created)
        now = datetime.now()
        now_ts = utc_millesecs_from_epoch(now)
        upload_time = now_ts - upload_start

        log.info(
            'Time for version {version} creation from upload: {delta}; '
            'created={created}; now={now}'.format(
                delta=upload_time, version=version, created=upload.created, now=now
            )
        )
        statsd.timing('devhub.version_created_from_upload', upload_time)
        statsd.incr(
            'devhub.version_created_from_upload.'
            f'{amo.ADDON_TYPE_CHOICES_API.get(addon.type, "")}'
        )

        VersionProvenance.from_version(
            version=version, source=upload.source, client_info=client_info
        )

        return version

    def get_url_path(self):
        if self.channel == amo.CHANNEL_UNLISTED:
            return ''
        return reverse('addons.versions', args=[self.addon.slug])

    def delete(self, hard=False):
        # To avoid a circular imports
        from .tasks import delete_preview_files, soft_block_versions

        log.info('Version deleted: %r (%s)', self, self.id)
        activity.log_create(amo.LOG.DELETE_VERSION, self.addon, str(self.version))

        if hard:
            super().delete()
        else:
            # By default we soft delete so we can keep the files for comparison
            # and a record of the version number.
            if hasattr(self, 'file') and self.file.status != amo.STATUS_DISABLED:
                # .file should always exist but we don't want to break delete regardless
                self.file.update(
                    status=amo.STATUS_DISABLED,
                    original_status=self.file.status,
                    status_disabled_reason=File.STATUS_DISABLED_REASONS.VERSION_DELETE,
                )
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

            soft_block_versions.delay(version_ids=[self.id])

    @property
    def is_user_disabled(self):
        return (
            self.file.status == amo.STATUS_DISABLED
            and self.file.status_disabled_reason
            == File.STATUS_DISABLED_REASONS.DEVELOPER
        )

    @is_user_disabled.setter
    def is_user_disabled(self, disable):
        # User wants to disable (and the File isn't already).
        if disable:
            if (file_ := self.file) and file_.status != amo.STATUS_DISABLED:
                activity.log_create(amo.LOG.DISABLE_VERSION, self.addon, self)
                file_.update(
                    original_status=file_.status,
                    status=amo.STATUS_DISABLED,
                    status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
                )
        # User wants to re-enable (and user did the disable, not Mozilla).
        else:
            if (
                (file_ := self.file)
                and file_.status_disabled_reason
                == File.STATUS_DISABLED_REASONS.DEVELOPER
            ):
                activity.log_create(amo.LOG.ENABLE_VERSION, self.addon, self)
                file_.update(
                    status=file_.original_status,
                    original_status=amo.STATUS_NULL,
                    status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
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

    def flag_if_sources_were_provided(self, user):
        from olympia.activity.utils import log_and_notify
        from olympia.reviewers.models import NeedsHumanReview

        from .tasks import call_webhooks_on_source_code_uploaded

        if self.source:
            # Add Activity Log, notifying staff, relevant reviewers and
            # other authors of the add-on.
            note = log_and_notify(amo.LOG.SOURCE_CODE_UPLOADED, None, user, self)

            if self.pending_rejection:
                reason = NeedsHumanReview.REASONS.PENDING_REJECTION_SOURCES_PROVIDED
                NeedsHumanReview.objects.create(version=self, reason=reason)

            if waffle.switch_is_active('enable-scanner-webhooks'):
                call_webhooks_on_source_code_uploaded.delay(
                    version_pk=self.pk, activity_log_id=note.id
                )

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

        Does nothing if the add-on is a langpack or if the current instance is
        unlisted.
        """
        if self.channel == amo.CHANNEL_LISTED and self.addon.type != amo.ADDON_LPAPP:
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

    def reset_due_date(self, due_date=None, should_have_due_date=None):
        """Sets a due date on this version, if it is eligible for one, or
        clears it if the version should not have a due date (see
        VersionManager.should_have_due_date for logic).

        If due_date is None then a new due date will only be set if the version
        doesn't already have one; otherwise the provided due_date will be be
        used to overwrite any value.

        If should_have_due_date is not None its value will be used instead of
        actually checking if the version should have a due date or not.

        Doesn't trigger post_save signal to avoid infinite loops
        since it can be triggered from Version.post_save callback.
        """

        if should_have_due_date is None:
            should_have_due_date = self.should_have_due_date

        if should_have_due_date:
            # if the version should have a due date and it doesn't, set one
            if not self.due_date or due_date:
                due_date = due_date or self.generate_due_date()
                log.info('Version %r (%s) due_date set to %s', self, self.id, due_date)
                self.update(due_date=due_date, _signal=False)
                if not self.reviewqueuehistory_set.filter(exit_date=None).exists():
                    self.reviewqueuehistory_set.create(
                        exit_date=None, original_due_date=due_date
                    )
        elif self.due_date:
            # otherwise it shouldn't have a due_date so clear it.
            log.info(
                'Version %r (%s) due_date of %s cleared', self, self.id, self.due_date
            )
            self.update(due_date=None, _signal=False)
            # The version left the queue - whether it was a reviewer action or
            # not, we record that here. Reviewer tools will update
            # review_decision_log separately if relevant.
            self.reviewqueuehistory_set.filter(exit_date=None).update(
                exit_date=datetime.now()
            )

    @use_primary_db
    def generate_due_date(self):
        """
        (Re)Generate a due date for this version, inheriting from the earliest
        due date possible from any other version with reasons that can trigger
        inheritance in the same channel if one exists, but only if the result
        would be at at earlier date than the default/existing one on the
        instance.
        """
        qs = (
            self.addon.versions_triggering_needs_human_review_inheritance(self.channel)
            .exclude(due_date=None)
            .exclude(id=self.pk)
            .values_list('due_date', flat=True)
            .order_by('-due_date')
        )
        due_date = qs.first()
        standard_or_existing_due_date = self.due_date or get_review_due_date()
        if not due_date or due_date > standard_or_existing_due_date:
            due_date = standard_or_existing_due_date
        return due_date

    @cached_property
    def is_ready_for_auto_approval(self):
        """Return whether or not this version could be *considered* for
        auto-approval.

        Does not necessarily mean that it would be auto-approved, just that it
        passes the most basic criteria to be considered a candidate by the
        auto_approve command."""
        return Version.objects.auto_approvable().filter(id=self.id).exists()

    @property
    def should_have_due_date(self):
        """Should this version have a due_date set, meaning it needs a manual review.

        See VersionManager.should_have_due_date for logic."""
        return Version.unfiltered.should_have_due_date().filter(id=self.id).exists()

    @property
    def was_auto_approved(self):
        """Return whether or not this version was auto-approved."""
        try:
            return self.autoapprovalsummary.verdict == amo.AUTO_APPROVED
        except Version.autoapprovalsummary.RelatedObjectDoesNotExist:
            pass
        return False

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

        promotions = self.addon.promoted_groups()

        if self != self.addon.current_version or (
            not promotions.exists()
            or not any(promotions.badged)
            or not any(promotions.listed_pre_review)
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
            promoted_group__group_id__in=promotions.group_id,
            version__in=previous_version,
        )
        return previous_approval.exists()

    @property
    def is_blocked(self):
        return hasattr(self, 'blockversion')

    @cached_property
    def blocklist_submission_id(self):
        from olympia.blocklist.models import BlocklistSubmission

        return (
            submission.id
            if self.id
            and (
                submission := BlocklistSubmission.get_submissions_from_version_id(
                    self.id
                ).last()
            )
            else 0
        )

    @property
    def pending_rejection(self):
        try:
            return self.reviewerflags.pending_rejection
        except VersionReviewerFlags.DoesNotExist:
            return None

    @property
    def pending_content_rejection(self):
        try:
            return self.reviewerflags.pending_content_rejection
        except VersionReviewerFlags.DoesNotExist:
            return None

    @property
    def pending_rejection_by(self):
        try:
            return self.reviewerflags.pending_rejection_by
        except VersionReviewerFlags.DoesNotExist:
            return None

    def get_review_status_for_auto_approval_and_delay_reject(self):
        status = None
        if (reviewer_flags := getattr(self, 'reviewerflags', None)) and (
            rejection_date := reviewer_flags.pending_rejection
        ):
            status = gettext('Delay-rejected, scheduled for %s') % rejection_date
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
    pending_rejection = models.DateTimeField(
        default=None, null=True, blank=True, db_index=True
    )
    pending_rejection_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.CASCADE
    )
    pending_content_rejection = models.BooleanField(null=True)
    pending_resolution_cinder_jobs = models.ManyToManyField(
        to='abuse.CinderJob', related_name='pending_rejections'
    )

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


class VersionProvenance(models.Model):
    version = models.ForeignKey(Version, primary_key=True, on_delete=models.CASCADE)
    source = models.PositiveSmallIntegerField(choices=amo.UPLOAD_SOURCE_CHOICES)
    client_info = models.CharField(max_length=255, null=True, default=None)

    @classmethod
    def from_version(cls, *, version, source, client_info):
        """Create a VersionProvenance from a Version and provenance info."""
        if client_info:
            # Truncate client_info if it was passed so that we can store it,
            # and extract web-ext version number if present to send a ping
            # about it.
            client_info_maxlength = cls._meta.get_field('client_info').max_length
            client_info = client_info[:client_info_maxlength]
            webext_version_match = re.match(r'web-ext/([\d\.]+)$', client_info or '')
            webext_version = (
                webext_version_match.group(1).replace('.', '_')
                if webext_version_match
                else None
            )
            if webext_version:
                if source == amo.UPLOAD_SOURCE_SIGNING_API:
                    formatted_source = 'signing.submission'
                elif source == amo.UPLOAD_SOURCE_ADDON_API:
                    formatted_source = 'addons.submission'
                else:
                    formatted_source = 'other'
                log.info(
                    'Version created from %s with webext_version %s:',
                    formatted_source,
                    webext_version,
                )
                statsd.incr(f'{formatted_source}.webext_version.{webext_version}')
        # Create the instance no matter what (client_info may be empty, that's
        # fine).
        return cls.objects.create(
            version=version, source=source, client_info=client_info
        )


def version_review_flags_save_signal(sender, instance, **kw):
    if not instance.pending_rejection:
        instance.pending_rejection_by = None
        instance.pending_content_rejection = None


models.signals.pre_save.connect(
    version_review_flags_save_signal,
    sender=VersionReviewerFlags,
    dispatch_uid='version_review_flags',
)


@receiver(
    models.signals.post_save,
    sender=VersionReviewerFlags,
    dispatch_uid='version_review_flags',
)
def update_due_date_for_pending_rejection_changes(sender, instance=None, **kwargs):
    instance.version.reset_due_date()


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


def inherit_due_date_if_nominated(sender, instance, **kw):
    """
    Ensure due date is inherited when the add-on is nominated for initial
    listed review.
    """
    if kw.get('raw'):
        return
    if instance.due_date is None and instance.addon.status == amo.STATUS_NOMINATED:
        instance.reset_due_date()


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
    inherit_due_date_if_nominated,
    sender=Version,
    dispatch_uid='inherit_due_date_if_nominated',
)
models.signals.pre_delete.connect(
    cleanup_version, sender=Version, dispatch_uid='cleanup_version'
)
models.signals.post_delete.connect(
    update_status, sender=Version, dispatch_uid='version_update_status'
)


class LicenseManager(ManagerBase):
    def builtins(self, cc=False, on_form=True):
        cc_q = Q(builtin__in=CC_LICENSES.keys())
        if not cc:
            cc_q = ~cc_q
        on_form_q = Q(builtin__in=FORM_LICENSES.keys()) if on_form else Q()
        return self.filter(on_form_q, cc_q, builtin__gt=0).order_by('builtin')


class License(ModelBase):
    OTHER = 0

    id = PositiveAutoField(primary_key=True)
    name = TranslatedField(max_length=200)
    builtin = models.PositiveIntegerField(default=OTHER)
    text = LinkifiedField(max_length=75000)

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

    @property
    def url(self):
        return ((constant := self._constant) and constant.url) or None


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
    originated_from = models.PositiveSmallIntegerField(
        choices=(
            (amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN, 'Unknown'),
            (amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC, 'Automatically determined'),
            (
                amo.APPVERSIONS_ORIGINATED_FROM_MIGRATION,
                'Automatically set by a migration',
            ),
            (
                amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER,
                'Set by developer through devhub or API',
            ),
            (
                amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST,
                'Set in the manifest (gecko key)',
            ),
            # Special case for Android, where compatibility information in the
            # manifest can come from the `gecko_android` key (with `gecko` as a
            # fallback).
            (
                amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID,
                'Set in the manifest (gecko_android key)',
            ),
        ),
        default=amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN,
        null=True,
    )

    # Range of Firefox for Android versions where compatibility should be
    # limited to add-ons with a promoted group that can be compatible with
    # Fenix (i.e. Line, Recommended).
    ANDROID_LIMITED_COMPATIBILITY_RANGE = (
        amo.MIN_VERSION_FENIX,
        amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
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

    def get_default_minimum_appversion(self):
        return AppVersion.objects.filter(application=self.application).get(
            version=amo.DEFAULT_WEBEXT_MIN_VERSIONS[amo.APPS_ALL[self.application]]
        )

    def get_default_maximum_appversion(self):
        return AppVersion.objects.filter(application=self.application).get(
            version=amo.DEFAULT_WEBEXT_MAX_VERSION
        )

    @property
    def locked_from_manifest(self):
        """Whether the manifest is the source of truth for this ApplicationsVersions or
        not.

        Currently only True if `gecko_android` is present in manifest.
        """
        return (
            self.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

    def __str__(self):
        pretty_application = self.get_application_display() if self.application else '?'
        try:
            if self.version.is_compatible_by_default:
                return gettext('{app} {min} and later').format(
                    app=pretty_application, min=self.min
                )
            return f'{pretty_application} {self.min} - {self.max}'
        except ObjectDoesNotExist:
            return pretty_application

    def version_range_contains_forbidden_compatibility(self):
        """
        Return whether the instance contains forbidden ranges.

        Used for Android to disallow non line/recommended to be compatible with
        Fenix before General Availability.
        """
        if self.application != amo.ANDROID.id:
            return False

        addon = self.version.addon

        if addon.type != amo.ADDON_EXTENSION:
            # We don't care about non-extension compatibility for this.
            return False

        # Recommended/line for Android are allowed to set compatibility in the
        # limited range.
        if addon.can_be_compatible_with_all_fenix_versions:
            return False

        # Range is expressed as a [closed, open) interval.
        limited_range_start = version_int(self.ANDROID_LIMITED_COMPATIBILITY_RANGE[0])
        limited_range_end = version_int(self.ANDROID_LIMITED_COMPATIBILITY_RANGE[1])

        # Min or max could be absent if it's a partial instance we'll be
        # completing later. Use default values in that case (increases the
        # chance that the range would be considered forbbiden, forcing caller
        # to provide a complete instance).
        min_ = getattr(self, 'min', None) or self.get_default_minimum_appversion()
        max_ = getattr(self, 'max', None) or self.get_default_maximum_appversion()

        return (
            min_.version_int < limited_range_end
            and max_.version_int >= limited_range_start
        )

    def save(self, *args, **kwargs):
        if (
            self.application == amo.ANDROID.id
            and self.version.addon.type == amo.ADDON_EXTENSION
        ):
            # Regardless of whether the compat information came from the
            # manifest, on Android we currently only allow non-promoted/line
            # extensions to be compatible with Fennec or Fenix that has general
            # availability, so we might need to override the compat data before
            # saving it.
            if self.version_range_contains_forbidden_compatibility():
                # Arbitrarily pick a range that makes sense and is valid.
                self.min = AppVersion.objects.filter(
                    application=amo.ANDROID.id,
                    version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
                ).first()
                self.max = AppVersion.objects.filter(
                    application=amo.ANDROID.id,
                    version=amo.DEFAULT_WEBEXT_MAX_VERSION,
                ).first()

            # In addition we need to set/clear strict compatibility.
            # If the range max is below the first Fenix version, then we need
            # to set strict_compatibility to True on the File to prevent that
            # version from being installed in Fenix. If it's not, then we need
            # to clear it if it was set.
            #
            # Strict compatibility also affects Desktop, so there is a slight
            # edge case if the developer had also set a max on desktop without
            # expecting it to be obeyed, but that should be fairly rare.
            if self.max.version_int < version_int(amo.MIN_VERSION_FENIX):
                strict_compatibility = True
            else:
                strict_compatibility = False
            if self.version.file.strict_compatibility != strict_compatibility:
                self.version.file.update(strict_compatibility=strict_compatibility)

        rval = super().save(*args, **kwargs)
        if hasattr(self.version, '_compatible_apps'):
            del self.version._compatible_apps
        return rval

    def delete(self, *args, **kwargs):
        if (
            self.application == amo.ANDROID.id
            and self.version.addon.type == amo.ADDON_EXTENSION
            and self.version.file.strict_compatibility
        ):
            self.version.file.update(strict_compatibility=False)
        return super().delete(*args, **kwargs)


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
