import re

from django.conf import settings

from rest_framework import exceptions, serializers

from olympia import amo
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.api.fields import ReverseChoiceField, TranslationSerializerField
from olympia.api.serializers import BaseESSerializer
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

from .models import (
    Addon, AddonFeatureCompatibility, CompatOverride, Persona, Preview,
    ReplacementAddon, attach_tags)


class AddonFeatureCompatibilitySerializer(serializers.ModelSerializer):
    e10s = ReverseChoiceField(
        choices=amo.E10S_COMPATIBILITY_CHOICES_API.items())

    class Meta:
        model = AddonFeatureCompatibility
        fields = ('e10s', )


class FileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    platform = ReverseChoiceField(choices=amo.PLATFORM_CHOICES_API.items())
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())
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
        # File.get_url_path() is a little different, it's already absolute, but
        # needs a src parameter that is appended as a query string.
        return obj.get_url_path(src='')


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
    name = serializers.SerializerMethodField()
    text = TranslationSerializerField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = License
        fields = ('id', 'name', 'text', 'url')

    def __init__(self, *args, **kwargs):
        super(LicenseSerializer, self).__init__(*args, **kwargs)
        self.db_name = TranslationSerializerField()
        self.db_name.bind('name', self)

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
                return unicode(license_constant.name)
            else:
                # Otherwise mock the dict with the default lang.
                lang = getattr(request, 'LANG', None) or settings.LANGUAGE_CODE
                return {lang: unicode(license_constant.name)}


class CompactLicenseSerializer(LicenseSerializer):
    class Meta:
        model = License
        fields = ('id', 'name', 'url')


class MinimalVersionSerializer(serializers.ModelSerializer):
    files = FileSerializer(source='all_files', many=True)

    class Meta:
        model = Version
        fields = ('id', 'files', 'reviewed', 'version')


class SimpleVersionSerializer(MinimalVersionSerializer):
    compatibility = serializers.SerializerMethodField()
    edit_url = serializers.SerializerMethodField()
    is_strict_compatibility_enabled = serializers.SerializerMethodField()
    license = CompactLicenseSerializer()
    release_notes = TranslationSerializerField(source='releasenotes')
    url = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = ('id', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'url', 'version')

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

    def get_url(self, obj):
        return absolutify(obj.get_url_path())


class SimpleESVersionSerializer(SimpleVersionSerializer):
    class Meta:
        model = Version
        # In ES, we don't have license and release notes info, so instead of
        # returning null, which is not necessarily true, we omit those fields
        # entirely.
        fields = ('id', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'reviewed', 'url',
                  'version')


class VersionSerializer(SimpleVersionSerializer):
    channel = ReverseChoiceField(choices=amo.CHANNEL_CHOICES_API.items())
    license = LicenseSerializer()

    class Meta:
        model = Version
        fields = ('id', 'channel', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'url', 'version')


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
            raise exceptions.ParseError(exc.message)

        version_qs = Version.objects.latest_public_compatible_with(
            application, appversions).filter(addon=addon)
        return version_qs.first() or addon.current_version


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
    contributions_url = serializers.URLField(source='contributions')
    current_version = CurrentVersionSerializer()
    description = TranslationSerializerField()
    developer_comments = TranslationSerializerField()
    edit_url = serializers.SerializerMethodField()
    has_eula = serializers.SerializerMethodField()
    has_privacy_policy = serializers.SerializerMethodField()
    homepage = TranslationSerializerField()
    icon_url = serializers.SerializerMethodField()
    icons = serializers.SerializerMethodField()
    is_source_public = serializers.BooleanField(source='view_source')
    is_featured = serializers.SerializerMethodField()
    name = TranslationSerializerField()
    previews = PreviewSerializer(many=True, source='current_previews')
    ratings = serializers.SerializerMethodField()
    ratings_url = serializers.SerializerMethodField()
    review_url = serializers.SerializerMethodField()
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())
    summary = TranslationSerializerField()
    support_email = TranslationSerializerField()
    support_url = TranslationSerializerField()
    tags = serializers.SerializerMethodField()
    theme_data = serializers.SerializerMethodField()
    type = ReverseChoiceField(choices=amo.ADDON_TYPE_CHOICES_API.items())
    url = serializers.SerializerMethodField()

    class Meta:
        model = Addon
        fields = (
            'id',
            'authors',
            'average_daily_users',
            'categories',
            'contributions_url',
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
            'theme_data',
            'type',
            'url',
            'weekly_downloads'
        )

    def to_representation(self, obj):
        data = super(AddonSerializer, self).to_representation(obj)
        if 'theme_data' in data and data['theme_data'] is None:
            data.pop('theme_data')
        if ('request' in self.context and
                'wrap_outgoing_links' in self.context['request'].GET):
            for key in ('homepage', 'support_url', 'contributions_url'):
                if key in data:
                    data[key] = self.outgoingify(data[key])
        if obj.type == amo.ADDON_PERSONA:
            if 'weekly_downloads' in data:
                # weekly_downloads don't make sense for lightweight themes.
                data.pop('weekly_downloads')

            if ('average_daily_users' in data and
                    not self.is_broken_persona(obj)):
                # In addition, their average_daily_users number must come from
                # the popularity field of the attached Persona.
                data['average_daily_users'] = obj.persona.popularity
        return data

    def outgoingify(self, data):
        if data:
            if isinstance(data, basestring):
                return get_outgoing_url(data)
            elif isinstance(data, dict):
                return {key: get_outgoing_url(value) if value else None
                        for key, value in data.items()}
        # None or empty string... don't bother.
        return data

    def get_categories(self, obj):
        # Return a dict of lists like obj.app_categories does, but exposing
        # slugs for keys and values instead of objects.
        return {
            app.short: [cat.slug for cat in obj.app_categories[app]]
            for app in obj.app_categories.keys()
        }

    def get_has_eula(self, obj):
        return bool(getattr(obj, 'has_eula', obj.eula))

    def get_is_featured(self, obj):
        # obj._is_featured is set from ES, so will only be present for list
        # requests.
        if not hasattr(obj, '_is_featured'):
            # Any featuring will do.
            obj._is_featured = obj.is_featured(app=None, lang=None)
        return obj._is_featured

    def get_has_privacy_policy(self, obj):
        return bool(getattr(obj, 'has_privacy_policy', obj.privacy_policy))

    def get_tags(self, obj):
        if not hasattr(obj, 'tag_list'):
            attach_tags([obj])
        # attach_tags() might not have attached anything to the addon, if it
        # had no tags.
        return getattr(obj, 'tag_list', [])

    def get_url(self, obj):
        # Use get_detail_url(), get_url_path() does an extra check on
        # current_version that is annoying in subclasses which don't want to
        # load that version.
        return absolutify(obj.get_detail_url())

    def get_edit_url(self, obj):
        return absolutify(obj.get_dev_url())

    def get_ratings_url(self, obj):
        return absolutify(obj.ratings_url)

    def get_review_url(self, obj):
        return absolutify(reverse('reviewers.review', args=[obj.pk]))

    def get_icon_url(self, obj):
        if self.is_broken_persona(obj):
            return absolutify(obj.get_default_icon_url(64))
        return absolutify(obj.get_icon_url(64))

    def get_icons(self, obj):
        # We're using only 32 and 64 for compatibility reasons with the
        # old search API. https://github.com/mozilla/addons-server/issues/7514
        if self.is_broken_persona(obj):
            get_icon = obj.get_default_icon_url
        else:
            get_icon = obj.get_icon_url

        return {str(size): absolutify(get_icon(size)) for size in (32, 64)}

    def get_ratings(self, obj):
        return {
            'average': obj.average_rating,
            'bayesian_average': obj.bayesian_rating,
            'count': obj.total_ratings,
            'text_count': obj.text_ratings_count,
        }

    def get_theme_data(self, obj):
        theme_data = None

        if obj.type == amo.ADDON_PERSONA and not self.is_broken_persona(obj):
            theme_data = obj.persona.theme_data
        return theme_data

    def is_broken_persona(self, obj):
        """Find out if the object is a Persona and either is missing its
        Persona instance or has a broken one.

        Call this everytime something in the serializer is suceptible to call
        something on the Persona instance, explicitly or not, to avoid 500
        errors and/or SQL queries in ESAddonSerializer."""
        try:
            # Sadly, https://code.djangoproject.com/ticket/14368 prevents us
            # from setting obj.persona = None in ESAddonSerializer.fake_object
            # below. This is fixed in Django 1.9, but in the meantime we work
            # around it by creating a Persona instance with a custom '_broken'
            # attribute indicating that it should not be used.
            if obj.type == amo.ADDON_PERSONA and (
                    obj.persona is None or hasattr(obj.persona, '_broken')):
                raise Persona.DoesNotExist
        except Persona.DoesNotExist:
            # We got a DoesNotExist exception, therefore the Persona does not
            # exist or is broken.
            return True
        # Everything is fine, move on.
        return False


class AddonSerializerWithUnlistedData(AddonSerializer):
    latest_unlisted_version = SimpleVersionSerializer()

    class Meta:
        model = Addon
        fields = AddonSerializer.Meta.fields + ('latest_unlisted_version',)


class ESAddonSerializer(BaseESSerializer, AddonSerializer):
    # Override various fields for related objects which we don't want to expose
    # data the same way than the regular serializer does (usually because we
    # some of the data is not indexed in ES).
    authors = BaseUserSerializer(many=True, source='listed_authors')
    current_version = SimpleESVersionSerializer()
    previews = ESPreviewSerializer(many=True, source='current_previews')

    datetime_fields = ('created', 'last_updated', 'modified')
    translated_fields = ('name', 'description', 'developer_comments',
                         'homepage', 'summary', 'support_email', 'support_url')

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
        # begins with an underscore. `latest_unlisted_version` is writeable
        # cached_property so we can directly write to them.
        obj._current_version = self.fake_version_object(
            obj, data.get('current_version'), amo.RELEASE_CHANNEL_LISTED)
        obj.latest_unlisted_version = self.fake_version_object(
            obj, data.get('latest_unlisted_version'),
            amo.RELEASE_CHANNEL_UNLISTED)

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

        obj._is_featured = data.get('is_featured', False)

        if data['type'] == amo.ADDON_PERSONA:
            persona_data = data.get('persona')
            if persona_data:
                obj.persona = Persona(
                    addon=obj,
                    accentcolor=persona_data['accentcolor'],
                    display_username=persona_data['author'],
                    header=persona_data['header'],
                    footer=persona_data['footer'],
                    # "New" Persona do not have a persona_id, it's a relic from
                    # old ones.
                    persona_id=0 if persona_data['is_new'] else 42,
                    textcolor=persona_data['textcolor'],
                    popularity=data.get('average_daily_users'),
                )
            else:
                # Sadly, https://code.djangoproject.com/ticket/14368 prevents
                # us from setting obj.persona = None. This is fixed in
                # Django 1.9, but in the meantime, work around it by creating
                # a Persona instance with a custom attribute indicating that
                # it should not be used.
                obj.persona = Persona()
                obj.persona._broken = True

        return obj


class ESAddonSerializerWithUnlistedData(
        ESAddonSerializer, AddonSerializerWithUnlistedData):
    # Because we're inheriting from ESAddonSerializer which does set its own
    # Meta class already, we have to repeat this from
    # AddonSerializerWithUnlistedData, but it beats having to redeclare the
    # fields...
    class Meta(AddonSerializerWithUnlistedData.Meta):
        fields = AddonSerializerWithUnlistedData.Meta.fields


class ESAddonAutoCompleteSerializer(ESAddonSerializer):
    class Meta(ESAddonSerializer.Meta):
        fields = ('id', 'icon_url', 'name', 'type', 'url')
        model = Addon

    def get_url(self, obj):
        # Addon.get_url_path() wants current_version to exist, but that's just
        # a safeguard. We don't care and don't want to fetch the current
        # version field to improve perf, so give it a fake one.
        obj._current_version = Version()
        return absolutify(obj.get_url_path())


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
    locale_disambiguation = serializers.CharField()
    current_compatible_version = serializers.SerializerMethodField()

    class Meta:
        model = Addon
        fields = ('id', 'current_compatible_version', 'default_locale', 'guid',
                  'locale_disambiguation', 'name', 'slug', 'target_locale',
                  'type', 'url', )

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
        return data


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
            if isinstance(user_id, basestring) and not user_id.isdigit():
                get_args.update(**{'author__username': user_id})
            else:
                get_args.update(**{'author': user_id})
            collection = Collection.objects.get(**get_args)
        except Collection.DoesNotExist:
            return []
        valid_q = Addon.objects.get_queryset().valid_q([amo.STATUS_PUBLIC])
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


class CompatOverrideSerializer(serializers.ModelSerializer):

    class VersionRangeSerializer(serializers.Serializer):
        class ApplicationSerializer(serializers.Serializer):
            name = serializers.CharField(source='app.pretty')
            id = serializers.IntegerField(source='app.id')
            min_version = serializers.CharField(source='min')
            max_version = serializers.CharField(source='max')
            guid = serializers.CharField(source='app.guid')

        addon_min_version = serializers.CharField(source='min')
        addon_max_version = serializers.CharField(source='max')
        applications = ApplicationSerializer(source='apps', many=True)

    addon_id = serializers.IntegerField()
    addon_guid = serializers.CharField(source='guid')
    version_ranges = VersionRangeSerializer(
        source='collapsed_ranges', many=True)

    class Meta:
        model = CompatOverride
        fields = ('addon_id', 'addon_guid', 'name', 'version_ranges')

    def get_addon_id(self, obj):
        return obj.addon_id
