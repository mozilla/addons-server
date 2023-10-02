import os
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File as DjangoFile
from django.urls import reverse
from django.utils.translation import gettext

from django_statsd.clients import statsd
from rest_framework import exceptions, serializers

from olympia import amo
from olympia.accounts.serializers import BaseUserSerializer
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import SafeStorage, remove_icons, slug_validator
from olympia.amo.validators import (
    CreateOnlyValidator,
    OneOrMoreLetterOrNumberCharacterValidator,
    PreventPartialUpdateValidator,
)
from olympia.api.exceptions import Conflict
from olympia.api.fields import (
    EmailTranslationField,
    LazyChoiceField,
    OutgoingURLTranslationField,
    ReverseChoiceField,
    SplitField,
    TranslationSerializerField,
)
from olympia.api.serializers import AMOModelSerializer, BaseESSerializer
from olympia.api.utils import is_gate_active
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.constants.applications import APP_IDS, APPS_ALL
from olympia.constants.base import ADDON_TYPE_CHOICES_API
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.constants.promoted import PROMOTED_GROUPS, RECOMMENDED
from olympia.core.languages import AMO_LANGUAGES
from olympia.files.models import File, FileUpload
from olympia.files.utils import DuplicateAddonID, parse_addon
from olympia.promoted.models import PromotedAddon
from olympia.ratings.utils import get_grouped_ratings
from olympia.search.filters import AddonAppVersionQueryParam
from olympia.tags.models import Tag
from olympia.users.models import RESTRICTION_TYPES, EmailUserRestriction, UserProfile
from olympia.versions.models import (
    ApplicationsVersions,
    License,
    Version,
    VersionPreview,
)

from .fields import (
    CategoriesSerializerField,
    ContributionSerializerField,
    ESLicenseNameSerializerField,
    ImageField,
    LicenseNameSerializerField,
    LicenseSlugSerializerField,
    SourceFileField,
    VersionCompatibilityField,
)
from .models import (
    Addon,
    AddonApprovalsCounter,
    AddonBrowserMapping,
    AddonUser,
    AddonUserPendingConfirmation,
    DeniedSlug,
    Preview,
    ReplacementAddon,
)
from .tasks import resize_icon, resize_preview
from .utils import (
    fetch_translations_from_addon,
    validate_version_number_is_gt_latest_signed_listed_version,
)
from .validators import (
    AddonDefaultLocaleValidator,
    AddonMetadataValidator,
    CanSetCompatibilityValidator,
    MatchingGuidValidator,
    NoFallbackDefaultLocaleValidator,
    ReviewedSourceFileValidator,
    VerifyMozillaTrademark,
    VersionAddonMetadataValidator,
    VersionLicenseValidator,
)


class FileSerializer(AMOModelSerializer):
    url = serializers.SerializerMethodField()
    platform = serializers.SerializerMethodField()
    status = ReverseChoiceField(choices=list(amo.STATUS_CHOICES_API.items()))
    permissions = serializers.ListField(child=serializers.CharField())
    optional_permissions = serializers.ListField(child=serializers.CharField())
    host_permissions = serializers.ListField(child=serializers.CharField())
    is_restart_required = serializers.SerializerMethodField()
    is_webextension = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = (
            'id',
            'created',
            'hash',
            'is_restart_required',
            'is_webextension',
            'is_mozilla_signed_extension',
            'platform',
            'size',
            'status',
            'url',
            'permissions',
            'optional_permissions',
            'host_permissions',
        )

    def get_url(self, obj):
        return obj.get_absolute_url()

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)
        if request and not is_gate_active(request, 'platform-shim'):
            data.pop('platform', None)
        if request and not is_gate_active(request, 'is-restart-required-shim'):
            data.pop('is_restart_required', None)
        if request and not is_gate_active(request, 'is-webextension-shim'):
            data.pop('is_webextension', None)
        return data

    def get_platform(self, obj):
        # platform is gone, but we need to keep the API backwards compatible so
        # fake it by just returning 'all' all the time.
        return 'all'

    def get_is_restart_required(self, obj):
        # is_restart_required is gone from the model and all addons are restartless now
        # so fake it for older API clients with False
        return False

    def get_is_webextension(self, obj):
        # is_webextension is always True these days because all addons are webextensions
        # but fake it for older API clients.
        return True


class LanguageToolFileSerializer(FileSerializer):
    permissions = serializers.SerializerMethodField()
    optional_permissions = serializers.SerializerMethodField()
    host_permissions = serializers.SerializerMethodField()

    def get_permissions(self, obj):
        # Language tools are not "real" webextensions, they don't have
        # permissions.
        return []

    def get_optional_permissions(self, obj):
        # Language tools are not "real" webextensions, they don't have
        # optional permissions.
        return []

    def get_host_permissions(self, obj):
        # Language tools are not "real" webextensions, they don't have
        # host permissions.
        return []


class ThisAddonDefault:
    requires_context = True

    def __call__(self, serializer_field):
        return serializer_field.context['view'].get_addon_object()


class PreviewSerializer(AMOModelSerializer):
    caption = TranslationSerializerField(required=False)
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    image_size = serializers.ReadOnlyField(source='image_dimensions')
    thumbnail_size = serializers.ReadOnlyField(source='thumbnail_dimensions')
    image = ImageField(write_only=True, validators=(CreateOnlyValidator(),))
    addon = serializers.HiddenField(default=ThisAddonDefault())

    class Meta:
        # Note: this serializer can also be used for VersionPreview.
        model = Preview
        fields = (
            'id',
            'addon',
            'caption',
            'image',
            'image_size',
            'image_url',
            'position',
            'thumbnail_size',
            'thumbnail_url',
        )

    def get_image_url(self, obj):
        return absolutify(obj.image_url)

    def get_thumbnail_url(self, obj):
        return absolutify(obj.thumbnail_url)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)
        if request and is_gate_active(request, 'del-preview-position'):
            data.pop('position', None)
        return data

    def validate(self, data):
        if self.context['view'].get_addon_object().type == amo.ADDON_STATICTHEME:
            raise exceptions.ValidationError(
                gettext('Previews cannot be created for themes.')
            )
        return data

    def create(self, validated_data):
        image = validated_data.pop('image')
        instance = super().create(validated_data)

        storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='previews')
        with storage.open(instance.original_path, 'wb') as original_file:
            for chunk in image.chunks():
                original_file.write(chunk)

        resize_preview.delay(
            instance.original_path,
            instance.pk,
            set_modified_on=instance.addon.serializable_reference(),
        )

        return instance

    def save(self, *args, **kwargs):
        instance = super().save(*args, **kwargs)
        ActivityLog.create(
            amo.LOG.CHANGE_MEDIA, instance.addon, user=self.context['request'].user
        )
        return instance


class ESPreviewSerializer(BaseESSerializer, PreviewSerializer):
    # Because we have translated fields and dates coming from ES, we can't use
    # a regular PreviewSerializer to handle previews for ESAddonSerializer.
    # Unfortunately we also need to get the class right (it can be either
    # Preview or VersionPreview) so fake_object() implementation in this class
    # does nothing, the instance has already been created by a parent
    # serializer.
    datetime_fields = ('modified',)
    translated_fields = ('caption',)

    def fake_object(self, data):
        return data


class LicenseSerializer(AMOModelSerializer):
    is_custom = serializers.SerializerMethodField()
    name = LicenseNameSerializerField(allow_null=True)
    text = TranslationSerializerField(allow_null=True)
    url = serializers.SerializerMethodField()
    slug = serializers.ReadOnlyField()

    class Meta:
        model = License
        fields = ('id', 'is_custom', 'name', 'slug', 'text', 'url')
        writeable_fields = ('name', 'text')
        read_only_fields = tuple(set(fields) - set(writeable_fields))
        validators = (NoFallbackDefaultLocaleValidator(),)

    def get_is_custom(self, obj):
        return not bool(obj.builtin)

    def get_url(self, obj):
        return obj.url or self.get_addon_license_url(obj)

    def get_addon_license_url(self, obj):
        # addons-frontend only supports an addon license url - not version specific -
        # currently so we just need the addon id.
        # We can get the addon via `instance.version_instance` which is set by
        # SimpleVersionSerializer.to_representation() while serializing.
        # Only get the addon license url for non-builtin licenses.
        if not obj.builtin and hasattr(obj, 'version_instance'):
            return absolutify(
                reverse('addons.license', args=[obj.version_instance.addon.slug])
            )
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request', None)
        if request and is_gate_active(request, 'del-version-license-is-custom'):
            data.pop('is_custom', None)
        if request and is_gate_active(request, 'del-version-license-slug'):
            data.pop('slug', None)
        return data

    def validate(self, data):
        if self.instance and not self.get_is_custom(self.instance):
            raise exceptions.ValidationError(
                gettext('Built in licenses can not be updated.')
            )
        return data


class CompactLicenseSerializer(LicenseSerializer):
    class Meta:
        model = License
        fields = ('id', 'is_custom', 'name', 'slug', 'url')


class MinimalVersionSerializer(AMOModelSerializer):
    file = FileSerializer(read_only=True)
    reviewed = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = ('id', 'file', 'reviewed', 'version')
        read_only_fields = fields

    def to_representation(self, instance):
        repr = super().to_representation(instance)
        request = self.context.get('request', None)
        if 'file' in repr and request and is_gate_active(request, 'version-files'):
            # In v3/v4 files is expected to be a list but now we only have one file.
            repr['files'] = [repr.pop('file')]
        return repr

    def get_reviewed(self, instance):
        return serializers.DateTimeField().to_representation(
            instance.file.approval_date or instance.human_review_date
        )


class LanguageToolVersionSerializer(MinimalVersionSerializer):
    file = LanguageToolFileSerializer(read_only=True)


class SimpleVersionSerializer(MinimalVersionSerializer):
    compatibility = VersionCompatibilityField(
        # Default to just Desktop Firefox as most of the times developers don't
        # develop their WebExtensions for Android.  See https://bit.ly/2QaMicU
        # Note that if the manifest contains `gecko_android`, an
        # ApplicationsVersions will automatically be created for Android at
        # submission time in addition to Firefox in Version.from_upload().
        source='compatible_apps',
        default=serializers.CreateOnlyDefault(
            {
                amo.APPS['firefox']: ApplicationsVersions(
                    application=amo.APPS['firefox'].id,
                )
            }
        ),
        read_only=True,
    )
    edit_url = serializers.SerializerMethodField()
    is_strict_compatibility_enabled = serializers.BooleanField(
        source='file.strict_compatibility', read_only=True
    )
    license = CompactLicenseSerializer(read_only=True)
    release_notes = TranslationSerializerField(required=False, read_only=True)

    class Meta:
        model = Version
        fields = (
            'id',
            'compatibility',
            'edit_url',
            'file',
            'is_strict_compatibility_enabled',
            'license',
            'release_notes',
            'reviewed',
            'version',
        )
        read_only_fields = fields

    def to_representation(self, instance):
        # Help the LicenseSerializer find the version we're currently serializing.
        if 'license' in self.fields and instance.license:
            instance.license.version_instance = instance
        return super().to_representation(instance)

    def get_edit_url(self, obj):
        return absolutify(
            obj.addon.get_dev_url('versions.edit', args=[obj.pk], prefix_only=True)
        )


class VersionSerializer(SimpleVersionSerializer):
    channel = ReverseChoiceField(
        choices=list(amo.CHANNEL_CHOICES_API.items()), read_only=True
    )
    license = SplitField(
        LicenseSlugSerializerField(required=False), LicenseSerializer(), read_only=True
    )

    class Meta:
        model = Version
        fields = (
            'id',
            'channel',
            'compatibility',
            'edit_url',
            'file',
            'is_strict_compatibility_enabled',
            'license',
            'release_notes',
            'reviewed',
            'version',
        )
        read_only_fields = fields

    def __init__(self, instance=None, data=serializers.empty, **kwargs):
        self.addon = kwargs.pop('addon', None)
        super().__init__(instance=instance, data=data, **kwargs)


class DeveloperVersionSerializer(VersionSerializer):
    custom_license = LicenseSerializer(
        write_only=True,
        required=False,
        source='license',
    )
    is_disabled = serializers.BooleanField(source='is_user_disabled', required=False)
    source = SourceFileField(
        required=False, allow_null=True, validators=(ReviewedSourceFileValidator(),)
    )
    upload = serializers.SlugRelatedField(
        slug_field='uuid',
        queryset=FileUpload.objects.all(),
        write_only=True,
        validators=(CreateOnlyValidator(),),
    )

    class Meta:
        model = Version
        validators = (
            CanSetCompatibilityValidator(),
            VersionLicenseValidator(),
            VersionAddonMetadataValidator(),
        )
        fields = (
            'id',
            'approval_notes',
            'channel',
            'compatibility',
            'custom_license',
            'edit_url',
            'file',
            'is_disabled',
            'is_strict_compatibility_enabled',
            'license',
            'release_notes',
            'reviewed',
            'source',
            'upload',
            'version',
        )
        writeable_fields = (
            'approval_notes',
            'compatibility',
            'custom_license',
            'is_disabled',
            'license',
            'release_notes',
            'source',
            'upload',
        )
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def get_fields(self):
        # We declare a bunch of fields as explicitly read_only in the parent
        # serializers so we need to overwrite that. We have explicitly set
        # read_only_fields just above so we use that as the source of truth.
        fields = super().get_fields()
        for name in fields:
            fields[name].read_only = name in self.Meta.read_only_fields
        return fields

    def to_representation(self, instance):
        # SourceFileField needs the version id to build the url.
        if 'source' in self.fields and instance.source:
            self.id = instance.id
        return super().to_representation(instance)

    @property
    def addon_type(self):
        # This will purposefully raise if we don't have the addon type yet.
        return (self.addon and self.addon.type) or self.parsed_data['type']

    def validate_upload(self, value):
        request = self.context.get('request')
        own_upload = request and request.user == value.user
        if not own_upload or not value.valid or value.validation_timeout:
            raise exceptions.ValidationError(gettext('Upload is not valid.'))
        # Parse the file to get and validate package data with the addon.
        try:
            self.parsed_data = parse_addon(value, addon=self.addon, user=request.user)
        except DuplicateAddonID as exc:
            raise Conflict({self.field_name: exc.messages})
        return value

    def validate_is_disabled(self, disable):
        # The Version.is_user_disabled setter just ignores any change it doesn't like,
        # but we'd like to raise instead if the value wouldn't be accepted.
        if disable and (version := self.instance):
            if (
                not version.is_user_disabled
                and version.file.status == amo.STATUS_DISABLED
            ):
                raise exceptions.ValidationError(gettext('File is already disabled.'))
            if not version.can_be_disabled_and_deleted():
                group = version.addon.promoted_group()
                msg = gettext(
                    'The latest approved version of this %s add-on cannot be deleted '
                    'because the previous version was not approved for %s promotion. '
                    'Please contact AMO Admins if you need help with this.'
                ) % (group.name, group.name)
                raise exceptions.ValidationError(msg)
        return disable

    def _check_for_existing_versions(self, version_string):
        # Make sure we don't already have this version.
        existing_versions = Version.unfiltered.filter(
            addon=self.addon, version=version_string
        )
        if existing_versions.exists():
            if existing_versions[0].deleted:
                msg = gettext(
                    'Version {version_string} was uploaded before and deleted.'
                )
            else:
                msg = gettext('Version {version_string} already exists.')
            raise Conflict({'version': [msg.format(version_string=version_string)]})

    def validate(self, data):
        if not self.instance:
            version_string = self.parsed_data.get('version')
            if self.addon:
                self._check_for_existing_versions(version_string)

                if data['upload'].channel == amo.CHANNEL_LISTED:
                    if error_message := (
                        validate_version_number_is_gt_latest_signed_listed_version(
                            self.addon, version_string
                        )
                    ):
                        raise exceptions.ValidationError({'version': error_message})
                    # Also check for submitting listed versions when disabled.
                    if self.addon.disabled_by_user:
                        raise exceptions.ValidationError(
                            gettext(
                                'Listed versions cannot be submitted while add-on is '
                                'disabled.'
                            )
                        )
        elif 'source' in data:
            # We need to manually trigger this as null/empty values aren't validated.
            try:
                ReviewedSourceFileValidator()(data['source'], self.fields['source'])
            except exceptions.ValidationError as exc:
                raise exceptions.ValidationError({'source': exc.detail})

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        upload = validated_data.get('upload')
        parsed_and_validated_data = {
            **self.parsed_data,
            **validated_data,
        }
        if isinstance(validated_data.get('license'), License):
            parsed_and_validated_data['license_id'] = validated_data['license'].id
        version = Version.from_upload(
            upload=upload,
            addon=self.addon or validated_data.get('addon'),
            channel=upload.channel,
            compatibility=validated_data.get('compatible_apps'),
            parsed_data=parsed_and_validated_data,
        )
        if isinstance(validated_data.get('license'), dict):
            # If we got a custom license lets create it and assign it to the version.
            version.update(
                license=self.fields['custom_license'].create(validated_data['license'])
            )
        upload.update(addon=version.addon)
        channel_text = amo.CHANNEL_CHOICES_API[upload.channel]
        if self.addon:
            # self.addon is None when creating a new add-on
            statsd.incr(f'addons.submission.version.{channel_text}')
            self.addon.update_status()
        else:
            statsd.incr(f'addons.submission.addon.{channel_text}')

        if 'source' in validated_data:
            version.source = validated_data['source']
            version.save()
            version.flag_if_sources_were_provided(user)

        return version

    def update(self, instance, validated_data):
        user = self.context['request'].user
        custom_license = (
            validated_data.pop('license')
            if isinstance(validated_data.get('license'), dict)
            else None
        )
        existing_maxs = {
            app: appver.max
            for app, appver in instance.compatible_apps.items()
            if appver
        }

        instance = super().update(instance, validated_data)
        if 'compatible_apps' in validated_data:
            instance.set_compatible_apps(validated_data['compatible_apps'])
            for app, appver in instance.compatible_apps.items():
                if appver and (
                    app not in existing_maxs or existing_maxs[app] != appver.max
                ):
                    ActivityLog.create(
                        amo.LOG.MAX_APPVERSION_UPDATED,
                        instance.addon,
                        instance,
                        user=user,
                        details={
                            'version': instance.version,
                            'target': appver.version.version,
                            'application': appver.application,
                        },
                    )
        if custom_license and (custom_license_field := self.fields['custom_license']):
            if (existing := instance.license) and existing.builtin == License.OTHER:
                custom_license_field.update(existing, custom_license)
            else:
                instance.update(license=custom_license_field.create(custom_license))
        if custom_license or 'license' in validated_data:
            ActivityLog.create(
                amo.LOG.CHANGE_LICENSE, instance.license, instance.addon, user=user
            )
        if 'source' in validated_data:
            instance.flag_if_sources_were_provided(user)
        return instance


class ListVersionSerializer(VersionSerializer):
    # When we're listing versions, we don't want to include the full license
    # text every time: we only do this for the version detail endpoint.
    license = CompactLicenseSerializer(read_only=True)


class DeveloperListVersionSerializer(DeveloperVersionSerializer):
    # As ListVersionSerializer, but based on DeveloperVersionSerializer instead
    license = CompactLicenseSerializer()


class SimpleDeveloperVersionSerializer(DeveloperVersionSerializer):
    # Used with DeveloperAddonSerializer - essentially SimpleVersionSerializer +
    # developer-only fields like source, approval_notes, etc.
    license = CompactLicenseSerializer(read_only=True)

    class Meta:
        model = Version
        fields = (
            'id',
            'approval_notes',
            'compatibility',
            'edit_url',
            'file',
            'is_disabled',
            'is_strict_compatibility_enabled',
            'license',
            'release_notes',
            'reviewed',
            'version',
            'source',
        )
        read_only_fields = fields


class CurrentVersionSerializer(SimpleVersionSerializer):
    def to_representation(self, obj):
        # If the add-on is a langpack, and `appversion` is passed, try to
        # determine the latest public compatible version and replace the obj
        # with the result. Because of the perf impact, only done for langpacks
        # in the detail API.
        request = self.context.get('request')
        view = self.context.get('view')
        addon = obj.addon
        if (
            request
            and request.GET.get('appversion')
            and getattr(view, 'action', None) == 'retrieve'
            and addon.type == amo.ADDON_LPAPP
        ):
            obj = self.get_current_compatible_version(addon)
        return super().to_representation(obj)

    def get_current_compatible_version(self, addon):
        """
        Return latest public version compatible with the app & appversion
        passed through the request, or fall back to addon.current_version if
        none is found.

        Only use on langpacks if the appversion parameter is present.
        """
        request = self.context.get('request')
        try:
            # AddonAppVersionQueryParam.get_values() returns (app_id, min, max)
            # but we want {'min': min, 'max': max}.
            value = AddonAppVersionQueryParam(request.GET).get_values()
            application = value[0]
            appversions = dict(zip(('min', 'max'), value[1:], strict=True))
        except ValueError as exc:
            raise exceptions.ParseError(str(exc))

        version_qs = Version.objects.latest_public_compatible_with(
            application, appversions
        ).filter(addon=addon)
        return version_qs.first() or addon.current_version


class ESCompactLicenseSerializer(BaseESSerializer, CompactLicenseSerializer):
    name = ESLicenseNameSerializerField(read_only=True)

    translated_fields = ('name',)

    def fake_object(self, data):
        # We just pass the data as the fake object will have been created
        # before by ESAddonSerializer.fake_version_object()
        return data


class ESCurrentVersionSerializer(BaseESSerializer, CurrentVersionSerializer):
    license = ESCompactLicenseSerializer(read_only=True)

    datetime_fields = ('reviewed',)
    translated_fields = ('release_notes',)

    def fake_object(self, data):
        # We just pass the data as the fake object will have been created
        # before by ESAddonSerializer.fake_version_object()
        return data


class AddonEulaPolicySerializer(AMOModelSerializer):
    eula = TranslationSerializerField()
    privacy_policy = TranslationSerializerField()

    class Meta:
        model = Addon
        fields = (
            'eula',
            'privacy_policy',
        )


class UserSerializerWithPictureUrl(BaseUserSerializer):
    picture_url = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + ('picture_url',)
        read_only_fields = fields


class AddonAuthorSerializer(AMOModelSerializer):
    name = serializers.CharField(source='user.name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    role = ReverseChoiceField(
        choices=list(amo.AUTHOR_CHOICES_API.items()), default=amo.AUTHOR_ROLE_OWNER
    )

    class Meta:
        model = AddonUser
        fields = ('user_id', 'name', 'email', 'listed', 'position', 'role')

        writeable_fields = ('listed', 'position', 'role')
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def validate_role(self, value):
        if (
            self.instance
            and value != amo.AUTHOR_ROLE_OWNER
            and not AddonUser.objects.filter(
                addon_id=self.instance.addon_id, role=amo.AUTHOR_ROLE_OWNER
            )
            .exclude(id=self.instance.id)
            .exists()
        ):
            raise serializers.ValidationError(
                gettext('Add-ons need at least one owner.')
            )
        return value

    def validate_listed(self, value):
        if (
            self.instance
            and value is not True
            and not AddonUser.objects.filter(
                addon_id=self.instance.addon_id, listed=True
            )
            .exclude(id=self.instance.id)
            .exists()
        ):
            raise serializers.ValidationError(
                gettext('Add-ons need at least one listed author.')
            )
        return value


class AddonPendingAuthorSerializer(AddonAuthorSerializer):
    user_id = serializers.IntegerField()
    addon = serializers.HiddenField(default=ThisAddonDefault())

    class Meta:
        model = AddonUserPendingConfirmation
        fields = ('addon', 'user_id', 'name', 'email', 'listed', 'role')

        writeable_fields = ('addon', 'user_id', 'listed', 'role')
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def validate_user_id(self, value):
        try:
            user = UserProfile.objects.get(id=value)
        except UserProfile.DoesNotExist:
            raise exceptions.ValidationError(gettext('Account not found.'))

        if not EmailUserRestriction.allow_email(
            user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ):
            raise exceptions.ValidationError(EmailUserRestriction.error_message)

        addon = self.context['view'].get_addon_object()
        if (
            addon.authors.filter(pk=user.pk).exists()
            or addon.addonuserpendingconfirmation_set.filter(user_id=user.pk).exists()
        ):
            raise exceptions.ValidationError(
                gettext('An author can only be present once.')
            )

        try:
            if user.display_name is None:
                raise DjangoValidationError('')  # raise so we can catch below.
            for validator in user._meta.get_field('display_name').validators:
                validator(user.display_name)
        except DjangoValidationError:
            raise exceptions.ValidationError(
                gettext(
                    'The account needs a display name before it can be added as an '
                    'author.'
                )
            )

        return value


class PromotedAddonSerializer(AMOModelSerializer):
    GROUP_CHOICES = [(group.id, group.api_name) for group in PROMOTED_GROUPS]
    apps = serializers.SerializerMethodField()
    category = ReverseChoiceField(choices=GROUP_CHOICES, source='group_id')

    class Meta:
        model = PromotedAddon
        fields = (
            'apps',
            'category',
        )

    def get_apps(self, obj):
        return [app.short for app in obj.approved_applications]


class AddonSerializer(AMOModelSerializer):
    authors = UserSerializerWithPictureUrl(
        many=True, source='listed_authors', read_only=True
    )
    categories = CategoriesSerializerField(source='all_categories', required=False)
    contributions_url = ContributionSerializerField(
        source='contributions', required=False
    )
    current_version = CurrentVersionSerializer(read_only=True)
    default_locale = serializers.ChoiceField(
        choices=list(AMO_LANGUAGES), required=False
    )
    description = TranslationSerializerField(required=False)
    developer_comments = TranslationSerializerField(required=False)
    edit_url = serializers.SerializerMethodField()
    has_eula = serializers.SerializerMethodField()
    has_privacy_policy = serializers.SerializerMethodField()
    homepage = OutgoingURLTranslationField(
        required=False,
    )
    icon_url = serializers.SerializerMethodField()
    icons = serializers.SerializerMethodField()
    icon = ImageField(
        required=False,
        allow_null=True,
        write_only=True,
        max_size_setting='MAX_ICON_UPLOAD_SIZE',
        require_square=True,
    )
    is_disabled = SplitField(
        serializers.BooleanField(source='disabled_by_user', required=False),
        serializers.BooleanField(),
    )
    is_source_public = serializers.SerializerMethodField()
    is_featured = serializers.SerializerMethodField()
    name = TranslationSerializerField(
        required=False,
        validators=[
            VerifyMozillaTrademark(),
            OneOrMoreLetterOrNumberCharacterValidator(),
        ],
    )
    previews = PreviewSerializer(many=True, source='current_previews', read_only=True)
    promoted = PromotedAddonSerializer(read_only=True)
    ratings = serializers.SerializerMethodField()
    ratings_url = serializers.SerializerMethodField()
    review_url = serializers.SerializerMethodField()
    status = ReverseChoiceField(
        choices=list(amo.STATUS_CHOICES_API.items()), read_only=True
    )
    summary = TranslationSerializerField(
        required=False,
        validators=[OneOrMoreLetterOrNumberCharacterValidator()],
    )
    support_email = EmailTranslationField(required=False)
    support_url = OutgoingURLTranslationField(required=False)
    tags = serializers.ListField(
        child=LazyChoiceField(choices=Tag.objects.values_list('tag_text', flat=True)),
        max_length=amo.MAX_TAGS,
        source='tag_list',
        required=False,
    )
    type = ReverseChoiceField(
        choices=list(amo.ADDON_TYPE_CHOICES_API.items()), read_only=True
    )
    url = serializers.SerializerMethodField()
    version = DeveloperVersionSerializer(
        write_only=True,  # Overridden in create/update to expose the version submitted.
        validators=(
            PreventPartialUpdateValidator(),
            MatchingGuidValidator(),
            # Include the default validators, except for VersionAddonMetadataValidator,
            # because we're using AddonMetadataValidator instead.
            *(
                val
                for val in DeveloperVersionSerializer.Meta.validators
                if val.__class__ != VersionAddonMetadataValidator
            ),
        ),
    )
    versions_url = serializers.SerializerMethodField()

    class Meta:
        model = Addon
        validators = (AddonMetadataValidator(), AddonDefaultLocaleValidator())
        fields = (
            'id',
            'authors',
            'average_daily_users',
            'categories',
            'contributions_url',
            'created',
            'current_version',
            'default_locale',
            'description',
            'developer_comments',
            'edit_url',
            'guid',
            'has_eula',
            'has_privacy_policy',
            'homepage',
            'icon_url',
            'icons',
            'icon',
            'is_disabled',
            'is_experimental',
            'is_featured',
            'is_source_public',
            'last_updated',
            'name',
            'previews',
            'promoted',
            'ratings',
            'ratings_url',
            'requires_payment',
            'review_url',
            'slug',
            'status',
            'summary',
            'support_email',
            'support_url',
            'tags',
            'type',
            'url',
            'version',
            'versions_url',
            'weekly_downloads',
        )
        writeable_fields = (
            'categories',
            'contributions_url',
            'default_locale',
            'description',
            'developer_comments',
            'homepage',
            'icon',
            'is_disabled',
            'is_experimental',
            'name',
            'requires_payment',
            'slug',
            'summary',
            'support_email',
            'support_url',
            'tags',
            'version',
        )
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)

        if request and is_gate_active(request, 'del-addons-created-field'):
            data.pop('created', None)
        if request and not is_gate_active(request, 'is-source-public-shim'):
            data.pop('is_source_public', None)
        if request and not is_gate_active(request, 'is-featured-addon-shim'):
            data.pop('is_featured', None)
        return data

    def get_has_eula(self, obj):
        return bool(getattr(obj, 'has_eula', obj.eula))

    def get_is_featured(self, obj):
        # featured is gone, but we need to keep the API backwards compatible so
        # fake it with promoted status instead.
        return bool(obj.promoted and obj.promoted.group == RECOMMENDED)

    def get_has_privacy_policy(self, obj):
        return bool(getattr(obj, 'has_privacy_policy', obj.privacy_policy))

    def get_url(self, obj):
        # Use absolutify(get_detail_url()), get_absolute_url() calls
        # get_url_path() which does an extra check on current_version that is
        # annoying in subclasses which don't want to load that version.
        return absolutify(obj.get_detail_url())

    def get_edit_url(self, obj):
        return absolutify(obj.get_dev_url())

    def get_ratings_url(self, obj):
        return absolutify(obj.ratings_url)

    def get_versions_url(self, obj):
        return absolutify(obj.versions_url)

    def get_review_url(self, obj):
        return absolutify(reverse('reviewers.review', args=[obj.pk]))

    def get_icon_url(self, obj):
        return absolutify(obj.get_icon_url(64))

    def get_icons(self, obj):
        get_icon = obj.get_icon_url

        return {str(size): absolutify(get_icon(size)) for size in amo.ADDON_ICON_SIZES}

    def get_ratings(self, obj):
        ratings = {
            'average': obj.average_rating,
            'bayesian_average': obj.bayesian_rating,
            'count': obj.total_ratings,
            'text_count': obj.text_ratings_count,
        }
        if (request := self.context.get('request', None)) and (
            grouped := get_grouped_ratings(request, obj)
        ):
            ratings['grouped_counts'] = grouped
        return ratings

    def get_is_source_public(self, obj):
        return False

    def run_validation(self, data=serializers.empty):
        # We want name and summary to be required fields so they're not cleared, but
        # *only* if this is an existing add-on with listed versions.
        # - see AddonMetadataValidator for new add-ons/versions.
        if self.instance and self.instance.has_listed_versions():
            for field in ('name', 'summary', 'categories'):
                if field in data:
                    self.fields[field].required = True
        if self.instance:
            self.fields['version'].addon = self.instance
        return super().run_validation(data)

    def validate_slug(self, value):
        slug_validator(value)

        if not self.instance or value != self.instance.slug:
            # DeniedSlug.blocked checks for all numeric slugs as well as being denied.
            if DeniedSlug.blocked(value):
                raise exceptions.ValidationError(
                    gettext('This slug cannot be used. Please choose another.')
                )

        return value

    def validate(self, data):
        if 'all_categories' in data:
            # We can't do this in a validate_categories function because we need
            # parsed_data from the version field; and we can't move this functionality
            # out into a validator class because we need to change `data` to drop dupes.
            addon_type = self.fields['version'].addon_type
            # filter out categories for the wrong type.
            # There might be dupes, e.g. "other" is a category for 2 types
            slugs = {cat.slug for cat in data['all_categories']}
            data['all_categories'] = [
                cat for cat in data['all_categories'] if cat.type == addon_type
            ]
            # double check we didn't lose any
            if slugs != {cat.slug for cat in data['all_categories']}:
                raise exceptions.ValidationError(
                    {'categories': gettext('Invalid category name.')}
                )
        return data

    def _save_icon(self, uploaded_icon):
        # This is only used during update. For create it's impossible to send the icon
        # as formdata while also sending json for `version`.
        destination = os.path.join(self.instance.get_icon_dir(), str(self.instance.id))
        if uploaded_icon:
            original = f'{destination}-original.png'

            storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='addon_icons')
            with storage.open(original, 'wb') as original_file:
                for chunk in uploaded_icon.chunks():
                    original_file.write(chunk)

            self.instance.update(icon_type=uploaded_icon.content_type)
            resize_icon.delay(
                original,
                destination,
                amo.ADDON_ICON_SIZES,
                set_modified_on=self.instance.serializable_reference(),
            )
        else:
            remove_icons(destination)
            self.instance.update(icon_type='')

    def log(self, instance, validated_data):
        validated_data = {**validated_data}  # we want to modify it, so take a copy
        user = self.context['request'].user

        if 'disabled_by_user' in validated_data:
            is_disabled = validated_data.pop('disabled_by_user')
            ActivityLog.create(
                amo.LOG.USER_DISABLE if is_disabled else amo.LOG.USER_ENABLE,
                instance,
                user=user,
            )
        if 'icon' in validated_data:
            validated_data.pop('icon')
            ActivityLog.create(amo.LOG.CHANGE_MEDIA, instance, user=user)
        if 'tag_list' in validated_data:
            # Tag.add_tag and Tag.remove_tag have their own logging so don't repeat it.
            validated_data.pop('tag_list')
        if 'version' in validated_data:
            # version is always a new object, and not a property either
            validated_data.pop('version')

        if validated_data:
            ActivityLog.create(
                amo.LOG.EDIT_PROPERTIES,
                instance,
                details=list(validated_data.keys()),
                user=user,
            )

    def create(self, validated_data):
        upload = validated_data.get('version').get('upload')

        addon = Addon.initialize_addon_from_upload(
            data={**self.fields['version'].parsed_data, **validated_data},
            upload=upload,
            channel=upload.channel,
            user=self.context['request'].user,
        )
        # Add categories
        addon.set_categories(validated_data.get('all_categories', []))
        addon.set_tag_list(validated_data.get('tag_list', []))
        addon.version = self.fields['version'].create(
            {**validated_data.get('version', {}), 'addon': addon}
        )
        # When creating, always return the version we just created in the
        # representation. It uses <instance>.version.
        self.fields['version'].write_only = False
        addon.update_status()

        return addon

    def update(self, instance, validated_data):
        fields_to_review = ('name', 'summary')
        old_metadata = (
            fetch_translations_from_addon(instance, fields_to_review)
            if instance.has_listed_versions()
            else None
        )

        old_slug = instance.slug

        if 'icon' in validated_data:
            self._save_icon(validated_data['icon'])
        instance = super().update(instance, validated_data)

        if old_metadata is not None and old_metadata != fetch_translations_from_addon(
            instance, fields_to_review
        ):
            statsd.incr('addons.submission.metadata_content_review_triggered')
            AddonApprovalsCounter.reset_content_for_addon(addon=instance)
        if 'all_categories' in validated_data:
            del instance.all_categories  # super.update will have set it.
            instance.set_categories(validated_data['all_categories'])
        if 'tag_list' in validated_data:
            del instance.tag_list  # super.update will have set it.
            instance.set_tag_list(validated_data['tag_list'])
        if 'version' in validated_data:
            instance.version = self.fields['version'].create(
                {**validated_data.get('version', {}), 'addon': instance}
            )
            # When updating, always return the version we just created in the
            # representation if there was one.
            self.fields['version'].write_only = False
        if 'slug' in validated_data:
            ActivityLog.create(
                amo.LOG.ADDON_SLUG_CHANGED, instance, old_slug, instance.slug
            )

        self.log(instance, validated_data)
        return instance


class DeveloperAddonSerializer(AddonSerializer):
    current_version = SimpleDeveloperVersionSerializer(read_only=True)
    latest_unlisted_version = SimpleDeveloperVersionSerializer(read_only=True)

    class Meta(AddonSerializer.Meta):
        fields = AddonSerializer.Meta.fields + ('latest_unlisted_version',)
        read_only_fields = tuple(
            set(fields) - set(AddonSerializer.Meta.writeable_fields)
        )


class SimpleAddonSerializer(AddonSerializer):
    class Meta:
        model = Addon
        fields = ('id', 'slug', 'name', 'icon_url')


class ESAddonSerializer(BaseESSerializer, AddonSerializer):
    # Override various fields for related objects which we don't want to expose
    # data the same way than the regular serializer does (usually because we
    # some of the data is not indexed in ES).
    authors = BaseUserSerializer(many=True, source='listed_authors')
    current_version = ESCurrentVersionSerializer()
    previews = ESPreviewSerializer(many=True, source='current_previews')
    tags = serializers.ListField(source='tag_list')
    _score = serializers.SerializerMethodField()

    datetime_fields = ('created', 'last_updated', 'modified')
    translated_fields = (
        'name',
        'description',
        'developer_comments',
        'homepage',
        'summary',
        'support_email',
        'support_url',
    )

    class Meta:
        model = Addon
        fields = AddonSerializer.Meta.fields + ('_score',)

    def fake_preview_object(self, obj, data, idx, model_class=Preview):
        # This is what ESPreviewSerializer.fake_object() would do, but we do
        # it here and make that fake_object() method a no-op in order to have
        # access to the right model_class to use - VersionPreview for static
        # themes, Preview for the rest.
        # We might not have position in ES; if not fake it with the list position.
        position = data.get('position', idx)
        preview = model_class(
            id=data['id'], created=None, sizes=data.get('sizes', {}), position=position
        )
        preview.addon = obj
        preview.version = obj.current_version
        preview_serializer = self.fields['previews'].child
        # Attach base attributes that have the same name/format in ES and in
        # the model.
        preview_serializer._attach_fields(preview, data, ('modified',))
        # Attach translations.
        preview_serializer._attach_translations(
            preview, data, preview_serializer.translated_fields
        )
        return preview

    def fake_file_object(self, obj, data):
        file_ = File(
            id=data['id'],
            created=self.handle_date(data['created']),
            hash=data['hash'],
            # The underlying file instance is fake, but the name really matters
            # to get the right filename in our download URLs.
            file=DjangoFile(None, name=data['filename']),
            is_mozilla_signed_extension=data.get('is_mozilla_signed_extension'),
            size=data['size'],
            status=data['status'],
            strict_compatibility=data.get('strict_compatibility', False),
            version=obj,
        )
        file_.permissions = data.get(
            'permissions', data.get('webext_permissions_list', [])
        )
        file_.optional_permissions = data.get('optional_permissions', [])
        file_.host_permissions = data.get('host_permissions', [])
        return file_

    def fake_version_object(self, obj, data, channel):
        if data:
            version = Version(
                addon=obj,
                created=self.handle_date(data['files'][0]['created']),
                id=data['id'],
                # This isn't the same thing, but for our purposes it'll do.
                human_review_date=self.handle_date(data['reviewed']),
                version=data['version'],
                channel=channel,
            )
            version.file = self.fake_file_object(version, data['files'][0])

            # In ES we store integers for the appversion info, we need to
            # convert it back to strings.
            compatible_apps = {}
            for app_id, compat_dict in data.get('compatible_apps', {}).items():
                app_name = APPS_ALL[int(app_id)]
                compatible_apps[app_name] = ApplicationsVersions(
                    min=AppVersion(
                        created=None, version=compat_dict.get('min_human', '')
                    ),
                    max=AppVersion(
                        created=None, version=compat_dict.get('max_human', '')
                    ),
                )
            version.compatible_apps = compatible_apps
            version_serializer = self.fields.get('current_version') or None
            if version_serializer:
                version_serializer._attach_translations(
                    version, data, version_serializer.translated_fields
                )
            if 'license' in data and version_serializer:
                license_serializer = version_serializer.fields['license']
                version.license = License(created=None, id=data['license']['id'])
                license_serializer._attach_fields(
                    version.license, data['license'], ('builtin',)
                )
                license_serializer._attach_translations(
                    version.license, data['license'], ('name',)
                )
            else:
                version.license = None
        else:
            version = None
        return version

    def fake_object(self, data):
        """Create a fake instance of Addon and related models from ES data."""
        obj = Addon(id=data['id'], created=None, slug=data['slug'])

        # Attach base attributes that have the same name/format in ES and in
        # the model.
        self._attach_fields(
            obj,
            data,
            (
                'average_daily_users',
                'bayesian_rating',
                'contributions',
                'created',
                'default_locale',
                'guid',
                'has_eula',
                'has_privacy_policy',
                'hotness',
                'icon_hash',
                'icon_type',
                'is_experimental',
                'last_updated',
                'modified',
                'requires_payment',
                'slug',
                'status',
                'type',
                'weekly_downloads',
            ),
        )

        # Attach attributes that do not have the same name/format in ES.
        obj.tag_list = data.get('tags', [])
        obj.all_categories = [
            CATEGORIES_BY_ID[cat_id]
            for cat_id in data.get('category', [])
            if cat_id in CATEGORIES_BY_ID
        ]

        # Not entirely accurate, but enough in the context of the search API.
        obj.disabled_by_user = data.get('is_disabled', False)

        # Attach translations (they require special treatment).
        self._attach_translations(obj, data, self.translated_fields)

        # Attach related models (also faking them). `current_version` is a
        # property we can't write to, so we use the underlying field which
        # begins with an underscore.
        data_version = data.get('current_version') or {}
        obj._current_version = self.fake_version_object(
            obj, data_version, amo.CHANNEL_LISTED
        )
        obj._current_version_id = data_version.get('id')

        data_authors = data.get('listed_authors', [])
        obj.listed_authors = [
            UserProfile(
                auth_id=None,
                id=data_author['id'],
                created=None,
                display_name=data_author['name'],
                username=data_author['username'],
                is_public=data_author.get('is_public', False),
            )
            for data_author in data_authors
        ]

        is_static_theme = data.get('type') == amo.ADDON_STATICTHEME
        preview_model_class = VersionPreview if is_static_theme else Preview
        obj.current_previews = [
            self.fake_preview_object(
                obj, preview_data, idx, model_class=preview_model_class
            )
            for idx, preview_data in enumerate(data.get('previews', []))
        ]

        promoted = data.get('promoted', None)
        if promoted:
            # set .approved_for_groups cached_property because it's used in
            # .approved_applications.
            approved_for_apps = promoted.get('approved_for_apps')
            obj.promoted = PromotedAddon(
                addon=obj,
                approved_application_ids=approved_for_apps,
                created=None,
                group_id=promoted['group_id'],
            )
            # we can safely regenerate these tuples because
            # .appproved_applications only cares about the current group
            obj._current_version.approved_for_groups = (
                (obj.promoted.group, APP_IDS.get(app_id))
                for app_id in approved_for_apps
            )
        else:
            obj.promoted = None

        ratings = data.get('ratings', {})
        obj.average_rating = ratings.get('average')
        obj.total_ratings = ratings.get('count')
        obj.text_ratings_count = ratings.get('text_count')

        return obj

    def get__score(self, obj):
        # es_meta is added by BaseESSerializer.to_representation() before DRF's
        # to_representation() is called, so it's present on all objects.
        return obj._es_meta['score']

    def get_ratings(self, obj):
        return {
            'average': obj.average_rating,
            'bayesian_average': obj.bayesian_rating,
            'count': obj.total_ratings,
            'text_count': obj.text_ratings_count,
        }

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request')
        if (
            request
            and '_score' in data
            and not is_gate_active(request, 'addons-search-_score-field')
        ):
            data.pop('_score')
        return data


class ESAddonAutoCompleteSerializer(ESAddonSerializer):
    class Meta(ESAddonSerializer.Meta):
        fields = ('id', 'icon_url', 'icons', 'name', 'promoted', 'type', 'url')
        model = Addon

    def get_url(self, obj):
        # Addon.get_absolute_url() calls get_url_path(), which wants
        # _current_version_id to exist, but that's just a safeguard. We don't
        # care and don't want to fetch the current version field to improve
        # perf, so give it a fake one.
        obj._current_version_id = 1
        return obj.get_absolute_url()


class StaticCategorySerializer(serializers.Serializer):
    """Serializes a `StaticCategory` as found in constants.categories"""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    application = serializers.SerializerMethodField()
    misc = serializers.BooleanField()
    type = serializers.SerializerMethodField()
    weight = serializers.IntegerField()
    description = serializers.CharField()

    def get_application(self, obj):
        return APPS_ALL[obj.application].short

    def get_type(self, obj):
        return ADDON_TYPE_CHOICES_API[obj.type]


class LanguageToolsSerializer(AddonSerializer):
    target_locale = serializers.CharField()
    current_compatible_version = serializers.SerializerMethodField()

    class Meta:
        model = Addon
        fields = (
            'id',
            'current_compatible_version',
            'default_locale',
            'guid',
            'name',
            'slug',
            'target_locale',
            'type',
            'url',
        )

    def get_current_compatible_version(self, obj):
        compatible_versions = getattr(obj, 'compatible_versions', None)
        if compatible_versions is not None:
            data = LanguageToolVersionSerializer(
                compatible_versions, context=self.context, many=True
            ).data
            try:
                # 99% of the cases there will only be one result, since most
                # language packs are automatically uploaded for a given app
                # version. If there are more, pick the most recent one.
                return data[0]
            except IndexError:
                # This should not happen, because the queryset in the view is
                # supposed to filter results to only return add-ons that do
                # have at least one compatible version, but let's not fail
                # too loudly if the unthinkable happens...
                pass
        return None

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context['request']
        if (
            AddonAppVersionQueryParam.query_param not in request.GET
            and 'current_compatible_version' in data
        ):
            data.pop('current_compatible_version')
        if request and is_gate_active(request, 'addons-locale_disambiguation-shim'):
            data['locale_disambiguation'] = None
        return data


class ReplacementAddonSerializer(AMOModelSerializer):
    replacement = serializers.SerializerMethodField()
    ADDON_PATH_REGEX = r"""/addon/(?P<addon_id>[^/<>"']+)/$"""
    COLLECTION_PATH_REGEX = (
        r"""/collections/(?P<user_id>[^/<>"']+)/(?P<coll_slug>[^/]+)/$"""
    )

    class Meta:
        model = ReplacementAddon
        fields = ('guid', 'replacement')

    def _get_addon_guid(self, addon_id):
        try:
            addon = Addon.objects.public().id_or_slug(addon_id).get()
        except Addon.DoesNotExist:
            return []
        return [addon.guid]

    def _get_collection_guids(self, user_id, collection_slug):
        try:
            get_args = {'slug': collection_slug, 'listed': True}
            if isinstance(user_id, str) and not user_id.isdigit():
                get_args.update(**{'author__username': user_id})
            else:
                get_args.update(**{'author': user_id})
            collection = Collection.objects.get(**get_args)
        except Collection.DoesNotExist:
            return []
        valid_q = Addon.objects.get_queryset().valid_q([amo.STATUS_APPROVED])
        return list(collection.addons.filter(valid_q).values_list('guid', flat=True))

    def get_replacement(self, obj):
        if obj.has_external_url():
            # It's an external url so no guids.
            return []
        addon_match = re.search(self.ADDON_PATH_REGEX, obj.path)
        if addon_match:
            return self._get_addon_guid(addon_match.group('addon_id'))

        coll_match = re.search(self.COLLECTION_PATH_REGEX, obj.path)
        if coll_match:
            return self._get_collection_guids(
                coll_match.group('user_id'), coll_match.group('coll_slug')
            )
        return []


class AddonBrowserMappingSerializer(AMOModelSerializer):
    # The source is an annotated field defined in `AddonBrowserMappingView`.
    addon_guid = serializers.CharField(source='addon__guid')

    class Meta:
        model = AddonBrowserMapping
        fields = (
            'addon_guid',
            'extension_id',
        )
