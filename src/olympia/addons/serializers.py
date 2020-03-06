import re
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.http.request import QueryDict

from rest_framework import exceptions, serializers

from olympia import amo
from olympia.accounts.serializers import (
    BaseUserSerializer, UserProfileBasketSyncSerializer)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.api.fields import (
    ESTranslationSerializerField, ReverseChoiceField,
    TranslationSerializerField)
from olympia.api.serializers import BaseESSerializer
from olympia.api.utils import is_gate_active
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.constants.applications import APPS_ALL
from olympia.constants.base import ADDON_TYPE_CHOICES_API
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.files.models import File
from olympia.search.filters import AddonAppVersionQueryParam
from olympia.users.models import UserProfile
from olympia.versions.models import (
    ApplicationsVersions, License, Version, VersionPreview)

from .models import Addon, Preview, ReplacementAddon, attach_tags


class FileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    platform = ReverseChoiceField(
        choices=list(amo.PLATFORM_CHOICES_API.items()))
    status = ReverseChoiceField(choices=list(amo.STATUS_CHOICES_API.items()))
    permissions = serializers.ListField(
        source='webext_permissions_list',
        child=serializers.CharField())
    is_restart_required = serializers.BooleanField()

    class Meta:
        model = File
        fields = ('id', 'created', 'hash', 'is_restart_required',
                  'is_webextension', 'is_mozilla_signed_extension',
                  'platform', 'size', 'status', 'url', 'permissions')

    def get_url(self, obj):
        return obj.get_absolute_url(src='')


class PreviewSerializer(serializers.ModelSerializer):
    caption = TranslationSerializerField()
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        # Note: this serializer can also be used for VersionPreview.
        model = Preview
        fields = ('id', 'caption', 'image_size', 'image_url', 'thumbnail_size',
                  'thumbnail_url')

    def get_image_url(self, obj):
        return absolutify(obj.image_url)

    def get_thumbnail_url(self, obj):
        return absolutify(obj.thumbnail_url)


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


class LicenseSerializer(serializers.ModelSerializer):
    is_custom = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    text = TranslationSerializerField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = License
        fields = ('id', 'is_custom', 'name', 'text', 'url')

    def __init__(self, *args, **kwargs):
        super(LicenseSerializer, self).__init__(*args, **kwargs)
        self.db_name = TranslationSerializerField()
        self.db_name.bind('name', self)

    def get_is_custom(self, obj):
        return not bool(obj.builtin)

    def get_url(self, obj):
        return obj.url or self.get_version_license_url(obj)

    def get_version_license_url(self, obj):
        # We need the version associated with the license, because that's where
        # the license_url() method lives. The problem is, normally we would not
        # be able to do that, because there can be multiple versions for a
        # given License. However, since we're serializing through a nested
        # serializer, we cheat and use `instance.version_instance` which is
        # set by SimpleVersionSerializer.to_representation() while serializing.
        # Only get the version license url for non-builtin licenses.
        if not obj.builtin and hasattr(obj, 'version_instance'):
            return absolutify(obj.version_instance.license_url())
        return None

    def get_name(self, obj):
        # See if there is a license constant
        license_constant = obj._constant
        if not license_constant:
            # If not fall back on the name in the database.
            return self.db_name.get_attribute(obj)
        else:
            request = self.context.get('request', None)
            if request and request.method == 'GET' and 'lang' in request.GET:
                # A single lang requested so return a flat string
                return str(license_constant.name)
            else:
                # Otherwise mock the dict with the default lang.
                lang = getattr(request, 'LANG', None) or settings.LANGUAGE_CODE
                return {lang: str(license_constant.name)}

    def to_representation(self, instance):
        data = super(LicenseSerializer, self).to_representation(instance)
        request = self.context.get('request', None)
        if request and is_gate_active(
                request, 'del-version-license-is-custom'):
            data.pop('is_custom', None)
        return data


class CompactLicenseSerializer(LicenseSerializer):
    class Meta:
        model = License
        fields = ('id', 'is_custom', 'name', 'url')


class MinimalVersionSerializer(serializers.ModelSerializer):
    channel = ReverseChoiceField(
        choices=list(amo.CHANNEL_CHOICES_API.items()))
    files = FileSerializer(source='all_files', many=True)

    class Meta:
        model = Version
        fields = ('id', 'files', 'reviewed', 'version')


class SimpleVersionSerializer(MinimalVersionSerializer):
    compatibility = serializers.SerializerMethodField()
    edit_url = serializers.SerializerMethodField()
    is_strict_compatibility_enabled = serializers.SerializerMethodField()
    license = CompactLicenseSerializer()
    release_notes = TranslationSerializerField()

    class Meta:
        model = Version
        fields = ('id', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'version')

    def to_representation(self, instance):
        # Help the LicenseSerializer find the version we're currently
        # serializing.
        if 'license' in self.fields and instance.license:
            instance.license.version_instance = instance
        return super(SimpleVersionSerializer, self).to_representation(instance)

    def get_compatibility(self, obj):
        return {
            app.short: {
                'min': compat.min.version if compat else (
                    amo.D2C_MIN_VERSIONS.get(app.id, '1.0')),
                'max': compat.max.version if compat else amo.FAKE_MAX_VERSION
            } for app, compat in obj.compatible_apps.items()
        }

    def get_edit_url(self, obj):
        return absolutify(obj.addon.get_dev_url(
            'versions.edit', args=[obj.pk], prefix_only=True))

    def get_is_strict_compatibility_enabled(self, obj):
        return any(file_.strict_compatibility for file_ in obj.all_files)


class VersionSerializer(SimpleVersionSerializer):
    license = LicenseSerializer()

    class Meta:
        model = Version
        fields = ('id', 'channel', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'version')


class CurrentVersionSerializer(SimpleVersionSerializer):
    def to_representation(self, obj):
        # If the add-on is a langpack, and `appversion` is passed, try to
        # determine the latest public compatible version and replace the obj
        # with the result. Because of the perf impact, only done for langpacks
        # in the detail API.
        request = self.context.get('request')
        view = self.context.get('view')
        addon = obj.addon
        if (request and request.GET.get('appversion') and
                getattr(view, 'action', None) == 'retrieve' and
                addon.type == amo.ADDON_LPAPP):
            obj = self.get_current_compatible_version(addon)
        return super(CurrentVersionSerializer, self).to_representation(obj)

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
            value = AddonAppVersionQueryParam(request).get_values()
            application = value[0]
            appversions = dict(zip(('min', 'max'), value[1:]))
        except ValueError as exc:
            raise exceptions.ParseError(str(exc))

        version_qs = Version.objects.latest_public_compatible_with(
            application, appversions).filter(addon=addon)
        return version_qs.first() or addon.current_version


class ESCompactLicenseSerializer(BaseESSerializer, CompactLicenseSerializer):
    translated_fields = ('name', )

    def __init__(self, *args, **kwargs):
        super(ESCompactLicenseSerializer, self).__init__(*args, **kwargs)
        self.db_name = ESTranslationSerializerField()
        self.db_name.bind('name', self)

    def fake_object(self, data):
        # We just pass the data as the fake object will have been created
        # before by ESAddonSerializer.fake_version_object()
        return data


class ESCurrentVersionSerializer(BaseESSerializer, CurrentVersionSerializer):
    license = ESCompactLicenseSerializer()

    datetime_fields = ('reviewed',)
    translated_fields = ('release_notes',)

    def fake_object(self, data):
        # We just pass the data as the fake object will have been created
        # before by ESAddonSerializer.fake_version_object()
        return data


class AddonEulaPolicySerializer(serializers.ModelSerializer):
    eula = TranslationSerializerField()
    privacy_policy = TranslationSerializerField()

    class Meta:
        model = Addon
        fields = (
            'eula',
            'privacy_policy',
        )


class AddonDeveloperSerializer(BaseUserSerializer):
    picture_url = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + (
            'picture_url',)
        read_only_fields = fields


class AddonSerializer(serializers.ModelSerializer):
    authors = AddonDeveloperSerializer(many=True, source='listed_authors')
    categories = serializers.SerializerMethodField()
    contributions_url = serializers.SerializerMethodField()
    current_version = CurrentVersionSerializer()
    description = TranslationSerializerField()
    developer_comments = TranslationSerializerField()
    edit_url = serializers.SerializerMethodField()
    has_eula = serializers.SerializerMethodField()
    has_privacy_policy = serializers.SerializerMethodField()
    homepage = TranslationSerializerField()
    icon_url = serializers.SerializerMethodField()
    icons = serializers.SerializerMethodField()
    is_source_public = serializers.SerializerMethodField()
    is_featured = serializers.SerializerMethodField()
    name = TranslationSerializerField()
    previews = PreviewSerializer(many=True, source='current_previews')
    ratings = serializers.SerializerMethodField()
    ratings_url = serializers.SerializerMethodField()
    review_url = serializers.SerializerMethodField()
    status = ReverseChoiceField(choices=list(amo.STATUS_CHOICES_API.items()))
    summary = TranslationSerializerField()
    support_email = TranslationSerializerField()
    support_url = TranslationSerializerField()
    tags = serializers.SerializerMethodField()
    type = ReverseChoiceField(choices=list(amo.ADDON_TYPE_CHOICES_API.items()))
    url = serializers.SerializerMethodField()

    class Meta:
        model = Addon
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
            'is_disabled',
            'is_experimental',
            'is_featured',
            'is_recommended',
            'is_source_public',
            'last_updated',
            'name',
            'previews',
            'public_stats',
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
            'weekly_downloads'
        )

    def to_representation(self, obj):
        data = super(AddonSerializer, self).to_representation(obj)
        request = self.context.get('request', None)

        if ('request' in self.context and
                'wrap_outgoing_links' in self.context['request'].GET):
            for key in ('homepage', 'support_url', 'contributions_url'):
                if key in data:
                    data[key] = self.outgoingify(data[key])
        if request and is_gate_active(request, 'del-addons-created-field'):
            data.pop('created', None)
        if request and not is_gate_active(request, 'is-source-public-shim'):
            data.pop('is_source_public', None)
        if request and not is_gate_active(request, 'is-featured-addon-shim'):
            data.pop('is_featured', None)
        return data

    def outgoingify(self, data):
        if data:
            if isinstance(data, str):
                return get_outgoing_url(data)
            elif isinstance(data, dict):
                return {key: get_outgoing_url(value) if value else None
                        for key, value in data.items()}
        # None or empty string... don't bother.
        return data

    def get_categories(self, obj):
        return {
            app_short_name: [cat.slug for cat in categories]
            for app_short_name, categories in obj.app_categories.items()
        }

    def get_has_eula(self, obj):
        return bool(getattr(obj, 'has_eula', obj.eula))

    def get_is_featured(self, obj):
        # featured is gone, but we need to keep the API backwards compatible so
        # fake it with recommended status instead.
        return obj.is_recommended

    def get_has_privacy_policy(self, obj):
        return bool(getattr(obj, 'has_privacy_policy', obj.privacy_policy))

    def get_tags(self, obj):
        if not hasattr(obj, 'tag_list'):
            attach_tags([obj])
        # attach_tags() might not have attached anything to the addon, if it
        # had no tags.
        return getattr(obj, 'tag_list', [])

    def get_url(self, obj):
        # Use absolutify(get_detail_url()), get_absolute_url() calls
        # get_url_path() which does an extra check on current_version that is
        # annoying in subclasses which don't want to load that version.
        return absolutify(obj.get_detail_url())

    def get_contributions_url(self, obj):
        if not obj.contributions:
            # don't add anything when it's not set.
            return obj.contributions
        parts = urlsplit(obj.contributions)
        query = QueryDict(parts.query, mutable=True)
        query.update(amo.CONTRIBUTE_UTM_PARAMS)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query.urlencode(),
             parts.fragment))

    def get_edit_url(self, obj):
        return absolutify(obj.get_dev_url())

    def get_ratings_url(self, obj):
        return absolutify(obj.ratings_url)

    def get_review_url(self, obj):
        return absolutify(reverse('reviewers.review', args=[obj.pk]))

    def get_icon_url(self, obj):
        return absolutify(obj.get_icon_url(64))

    def get_icons(self, obj):
        get_icon = obj.get_icon_url

        return {str(size): absolutify(get_icon(size))
                for size in amo.ADDON_ICON_SIZES}

    def get_ratings(self, obj):
        return {
            'average': obj.average_rating,
            'bayesian_average': obj.bayesian_rating,
            'count': obj.total_ratings,
            'text_count': obj.text_ratings_count,
        }

    def get_is_source_public(self, obj):
        return False


class AddonSerializerWithUnlistedData(AddonSerializer):
    latest_unlisted_version = SimpleVersionSerializer()

    class Meta:
        model = Addon
        fields = AddonSerializer.Meta.fields + ('latest_unlisted_version',)


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
    _score = serializers.SerializerMethodField()

    datetime_fields = ('created', 'last_updated', 'modified')
    translated_fields = ('name', 'description', 'developer_comments',
                         'homepage', 'summary', 'support_email', 'support_url')

    class Meta:
        model = Addon
        fields = AddonSerializer.Meta.fields + ('_score', )

    def fake_preview_object(self, obj, data, model_class=Preview):
        # This is what ESPreviewSerializer.fake_object() would do, but we do
        # it here and make that fake_object() method a no-op in order to have
        # access to the right model_class to use - VersionPreview for static
        # themes, Preview for the rest.
        preview = model_class(id=data['id'], sizes=data.get('sizes', {}))
        preview.addon = obj
        preview.version = obj.current_version
        preview_serializer = self.fields['previews'].child
        # Attach base attributes that have the same name/format in ES and in
        # the model.
        preview_serializer._attach_fields(preview, data, ('modified',))
        # Attach translations.
        preview_serializer._attach_translations(
            preview, data, preview_serializer.translated_fields)
        return preview

    def fake_file_object(self, obj, data):
        file_ = File(
            id=data['id'], created=self.handle_date(data['created']),
            hash=data['hash'], filename=data['filename'],
            is_webextension=data.get('is_webextension'),
            is_mozilla_signed_extension=data.get(
                'is_mozilla_signed_extension'),
            is_restart_required=data.get('is_restart_required', False),
            platform=data['platform'], size=data['size'],
            status=data['status'],
            strict_compatibility=data.get('strict_compatibility', False),
            version=obj)
        file_.webext_permissions_list = data.get('webext_permissions_list', [])
        return file_

    def fake_version_object(self, obj, data, channel):
        if data:
            version = Version(
                addon=obj, id=data['id'],
                reviewed=self.handle_date(data['reviewed']),
                version=data['version'], channel=channel)
            version.all_files = [
                self.fake_file_object(version, file_data)
                for file_data in data.get('files', [])
            ]

            # In ES we store integers for the appversion info, we need to
            # convert it back to strings.
            compatible_apps = {}
            for app_id, compat_dict in data.get('compatible_apps', {}).items():
                app_name = APPS_ALL[int(app_id)]
                compatible_apps[app_name] = ApplicationsVersions(
                    min=AppVersion(version=compat_dict.get('min_human', '')),
                    max=AppVersion(version=compat_dict.get('max_human', '')))
            version._compatible_apps = compatible_apps
            version_serializer = self.fields['current_version']
            version_serializer._attach_translations(
                version, data, version_serializer.translated_fields)
            if 'license' in data:
                license_serializer = version_serializer.fields['license']
                version.license = License(id=data['license']['id'])
                license_serializer._attach_fields(
                    version.license, data['license'], ('builtin', 'url'))
                # Can't use license_serializer._attach_translations() directly
                # because 'name' is a SerializerMethodField, not an
                # ESTranslatedField.
                license_serializer.db_name.attach_translations(
                    version.license, data['license'], 'name')
            else:
                version.license = None
        else:
            version = None
        return version

    def fake_object(self, data):
        """Create a fake instance of Addon and related models from ES data."""
        obj = Addon(id=data['id'], slug=data['slug'])

        # Attach base attributes that have the same name/format in ES and in
        # the model.
        self._attach_fields(
            obj, data, (
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
                'is_recommended',
                'last_updated',
                'modified',
                'public_stats',
                'requires_payment',
                'slug',
                'status',
                'type',
                'view_source',
                'weekly_downloads'
            )
        )

        # Attach attributes that do not have the same name/format in ES.
        obj.tag_list = data.get('tags', [])
        obj.all_categories = [
            CATEGORIES_BY_ID[cat_id] for cat_id in data.get('category', [])]

        # Not entirely accurate, but enough in the context of the search API.
        obj.disabled_by_user = data.get('is_disabled', False)

        # Attach translations (they require special treatment).
        self._attach_translations(obj, data, self.translated_fields)

        # Attach related models (also faking them). `current_version` is a
        # property we can't write to, so we use the underlying field which
        # begins with an underscore.
        data_version = data.get('current_version') or {}
        obj._current_version = self.fake_version_object(
            obj, data_version, amo.RELEASE_CHANNEL_LISTED)
        obj._current_version_id = data_version.get('id')

        data_authors = data.get('listed_authors', [])
        obj.listed_authors = [
            UserProfile(
                id=data_author['id'], display_name=data_author['name'],
                username=data_author['username'],
                is_public=data_author.get('is_public', False))
            for data_author in data_authors
        ]

        is_static_theme = data.get('type') == amo.ADDON_STATICTHEME
        preview_model_class = VersionPreview if is_static_theme else Preview
        obj.current_previews = [
            self.fake_preview_object(
                obj, preview_data, model_class=preview_model_class)
            for preview_data in data.get('previews', [])
        ]

        ratings = data.get('ratings', {})
        obj.average_rating = ratings.get('average')
        obj.total_ratings = ratings.get('count')
        obj.text_ratings_count = ratings.get('text_count')

        return obj

    def get__score(self, obj):
        # es_meta is added by BaseESSerializer.to_representation() before DRF's
        # to_representation() is called, so it's present on all objects.
        return obj._es_meta['score']

    def to_representation(self, obj):
        data = super(ESAddonSerializer, self).to_representation(obj)
        request = self.context.get('request')
        if request and '_score' in data and not is_gate_active(
                request, 'addons-search-_score-field'):
            data.pop('_score')
        return data


class ESAddonAutoCompleteSerializer(ESAddonSerializer):
    class Meta(ESAddonSerializer.Meta):
        fields = ('id', 'icon_url', 'is_recommended', 'name', 'type', 'url')
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
        fields = ('id', 'current_compatible_version', 'default_locale', 'guid',
                  'name', 'slug', 'target_locale', 'type', 'url', )

    def get_current_compatible_version(self, obj):
        compatible_versions = getattr(obj, 'compatible_versions', None)
        if compatible_versions is not None:
            data = MinimalVersionSerializer(
                compatible_versions, many=True).data
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
        data = super(LanguageToolsSerializer, self).to_representation(obj)
        request = self.context['request']
        if (AddonAppVersionQueryParam.query_param not in request.GET and
                'current_compatible_version' in data):
            data.pop('current_compatible_version')
        if request and is_gate_active(
                request, 'addons-locale_disambiguation-shim'):
            data['locale_disambiguation'] = None
        return data


class VersionBasketSerializer(SimpleVersionSerializer):
    class Meta:
        model = Version
        fields = ('id', 'compatibility', 'is_strict_compatibility_enabled',
                  'version')


class AddonBasketSyncSerializer(AddonSerializerWithUnlistedData):
    # We want to send all authors to basket, not just listed ones, and have
    # the full basket-specific serialization.
    authors = UserProfileBasketSyncSerializer(many=True)
    name = serializers.SerializerMethodField()
    latest_unlisted_version = VersionBasketSerializer()
    current_version = VersionBasketSerializer()

    class Meta:
        model = Addon
        fields = ('authors', 'average_daily_users', 'categories',
                  'current_version', 'default_locale', 'guid', 'id',
                  'is_disabled', 'is_recommended', 'last_updated',
                  'latest_unlisted_version', 'name', 'ratings', 'slug',
                  'status', 'type')
        read_only_fields = fields

    def get_name(self, obj):
        # Basket doesn't want translations, we run the serialization task under
        # the add-on default locale so we can just return the name as string.
        return str(obj.name)


class ReplacementAddonSerializer(serializers.ModelSerializer):
    replacement = serializers.SerializerMethodField()
    ADDON_PATH_REGEX = r"""/addon/(?P<addon_id>[^/<>"']+)/$"""
    COLLECTION_PATH_REGEX = (
        r"""/collections/(?P<user_id>[^/<>"']+)/(?P<coll_slug>[^/]+)/$""")

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
        return list(
            collection.addons.filter(valid_q).values_list('guid', flat=True))

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
                coll_match.group('user_id'), coll_match.group('coll_slug'))
        return []
