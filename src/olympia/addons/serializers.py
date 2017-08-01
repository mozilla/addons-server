from rest_framework import serializers

from olympia import amo
from olympia.addons.models import (
    Addon, AddonFeatureCompatibility, attach_tags, Persona, Preview)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.api.fields import ReverseChoiceField, TranslationSerializerField
from olympia.api.serializers import BaseESSerializer
from olympia.applications.models import AppVersion
from olympia.constants.applications import APPS_ALL
from olympia.constants.base import ADDON_TYPE_CHOICES_API
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.files.models import File
from olympia.users.models import UserProfile
from olympia.users.serializers import (
    AddonDeveloperSerializer, BaseUserSerializer)
from olympia.versions.models import ApplicationsVersions, License, Version


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
                  'is_webextension', 'platform', 'size', 'status', 'url',
                  'permissions')

    def get_url(self, obj):
        # File.get_url_path() is a little different, it's already absolute, but
        # needs a src parameter that is appended as a query string.
        return obj.get_url_path(src='')


class PreviewSerializer(serializers.ModelSerializer):
    caption = TranslationSerializerField()
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Preview
        fields = ('id', 'caption', 'image_url', 'thumbnail_url')

    def get_image_url(self, obj):
        return absolutify(obj.image_url)

    def get_thumbnail_url(self, obj):
        return absolutify(obj.thumbnail_url)


class ESPreviewSerializer(BaseESSerializer, PreviewSerializer):
    # We could do this in ESAddonSerializer, but having a specific serializer
    # that inherits from BaseESSerializer for previews allows us to handle
    # translations more easily.
    datetime_fields = ('modified',)
    translated_fields = ('caption',)

    def fake_object(self, data):
        """Create a fake instance of Preview from ES data."""
        obj = Preview(id=data['id'])

        # Attach base attributes that have the same name/format in ES and in
        # the model.
        self._attach_fields(obj, data, ('modified',))

        # Attach translations.
        self._attach_translations(obj, data, self.translated_fields)

        return obj


class LicenseSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    text = TranslationSerializerField()

    class Meta:
        model = License
        fields = ('id', 'name', 'text', 'url')


class CompactLicenseSerializer(LicenseSerializer):
    class Meta:
        model = License
        fields = ('id', 'name', 'url')


class SimpleVersionSerializer(serializers.ModelSerializer):
    compatibility = serializers.SerializerMethodField()
    is_strict_compatibility_enabled = serializers.SerializerMethodField()
    edit_url = serializers.SerializerMethodField()
    files = FileSerializer(source='all_files', many=True)
    license = CompactLicenseSerializer()
    url = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = ('id', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license', 'reviewed',
                  'url', 'version')

    def get_url(self, obj):
        return absolutify(obj.get_url_path())

    def get_edit_url(self, obj):
        return absolutify(obj.addon.get_dev_url(
            'versions.edit', args=[obj.pk], prefix_only=True))

    def get_compatibility(self, obj):
        if obj.addon.type in amo.NO_COMPAT:
            return {}
        return {app.short: {'min': compat.min.version,
                            'max': compat.max.version}
                for app, compat in obj.compatible_apps.items()}

    def get_is_strict_compatibility_enabled(self, obj):
        return any(file_.strict_compatibility for file_ in obj.all_files)


class VersionSerializer(SimpleVersionSerializer):
    channel = ReverseChoiceField(choices=amo.CHANNEL_CHOICES_API.items())
    license = LicenseSerializer()
    release_notes = TranslationSerializerField(source='releasenotes')

    class Meta:
        model = Version
        fields = ('id', 'channel', 'compatibility', 'edit_url', 'files',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'url', 'version')


class AddonEulaPolicySerializer(serializers.ModelSerializer):
    eula = TranslationSerializerField()
    privacy_policy = TranslationSerializerField()

    class Meta:
        model = Addon
        fields = (
            'eula',
            'privacy_policy',
        )


class AddonSerializer(serializers.ModelSerializer):
    authors = AddonDeveloperSerializer(many=True, source='listed_authors')
    categories = serializers.SerializerMethodField()
    current_beta_version = SimpleVersionSerializer()
    current_version = SimpleVersionSerializer()
    description = TranslationSerializerField()
    edit_url = serializers.SerializerMethodField()
    has_eula = serializers.SerializerMethodField()
    has_privacy_policy = serializers.SerializerMethodField()
    homepage = TranslationSerializerField()
    icon_url = serializers.SerializerMethodField()
    is_source_public = serializers.BooleanField(source='view_source')
    is_featured = serializers.SerializerMethodField()
    name = TranslationSerializerField()
    previews = PreviewSerializer(many=True, source='all_previews')
    ratings = serializers.SerializerMethodField()
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
            'current_beta_version',
            'current_version',
            'default_locale',
            'description',
            'edit_url',
            'guid',
            'has_eula',
            'has_privacy_policy',
            'homepage',
            'icon_url',
            'is_disabled',
            'is_experimental',
            'is_featured',
            'is_source_public',
            'last_updated',
            'name',
            'previews',
            'public_stats',
            'ratings',
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
        # Set this so BaseUserSerializer doesn't need to do a query
        self.context['is_developer'] = True
        data = super(AddonSerializer, self).to_representation(obj)
        if 'theme_data' in data and data['theme_data'] is None:
            data.pop('theme_data')
        if 'homepage' in data:
            data['homepage'] = self.outgoingify(data['homepage'])
        if 'support_url' in data:
            data['support_url'] = self.outgoingify(data['support_url'])
        return data

    def outgoingify(self, data):
        if isinstance(data, basestring):
            return get_outgoing_url(data)
        elif isinstance(data, dict):
            return {key: get_outgoing_url(value) if value else None
                    for key, value in data.items()}
        # Probably None... don't bother.
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
        return absolutify(obj.get_url_path())

    def get_edit_url(self, obj):
        return absolutify(obj.get_dev_url())

    def get_review_url(self, obj):
        return absolutify(reverse('editors.review', args=[obj.pk]))

    def get_icon_url(self, obj):
        if self.is_broken_persona(obj):
            return absolutify(obj.get_default_icon_url(64))
        return absolutify(obj.get_icon_url(64))

    def get_ratings(self, obj):
        return {
            'average': obj.average_rating,
            'bayesian_average': obj.bayesian_rating,
            'count': obj.total_reviews,
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


class ESBaseAddonSerializer(BaseESSerializer):
    datetime_fields = ('created', 'last_updated', 'modified')
    translated_fields = ('name', 'description', 'homepage', 'summary',
                         'support_email', 'support_url')

    def fake_file_object(self, obj, data):
        file_ = File(
            id=data['id'], created=self.handle_date(data['created']),
            hash=data['hash'], filename=data['filename'],
            is_webextension=data.get('is_webextension'),
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
            version.compatible_apps = compatible_apps
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
                'created',
                'default_locale',
                'guid',
                'has_eula',
                'has_privacy_policy',
                'hotness',
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
        # begins with an underscore. `current_beta_version` and
        # `latest_unlisted_version` are writeable cached_property so we can
        # directly write to them.
        obj.current_beta_version = self.fake_version_object(
            obj, data.get('current_beta_version'), amo.RELEASE_CHANNEL_LISTED)
        obj._current_version = self.fake_version_object(
            obj, data.get('current_version'), amo.RELEASE_CHANNEL_LISTED)
        obj.latest_unlisted_version = self.fake_version_object(
            obj, data.get('latest_unlisted_version'),
            amo.RELEASE_CHANNEL_UNLISTED)

        data_authors = data.get('listed_authors', [])
        obj.listed_authors = [
            UserProfile(
                id=data_author['id'], display_name=data_author['name'],
                username=data_author['username'])
            for data_author in data_authors
        ]

        # We set obj.all_previews to the raw preview data because
        # ESPreviewSerializer will handle creating the fake Preview object
        # for us when its to_representation() method is called.
        obj.all_previews = data.get('previews', [])

        obj.average_rating = data.get('ratings', {}).get('average')
        obj.total_reviews = data.get('ratings', {}).get('count')

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
                    textcolor=persona_data['textcolor']
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


class ESAddonSerializer(ESBaseAddonSerializer, AddonSerializer):
    # Override authors because we don't want picture_url in serializer.
    authors = BaseUserSerializer(many=True, source='listed_authors')
    previews = ESPreviewSerializer(many=True, source='all_previews')


class ESAddonSerializerWithUnlistedData(
        ESBaseAddonSerializer, AddonSerializerWithUnlistedData):
    # Override authors because we don't want picture_url in serializer.
    authors = BaseUserSerializer(many=True, source='listed_authors')
    previews = ESPreviewSerializer(many=True, source='all_previews')


class ESAddonAutoCompleteSerializer(ESAddonSerializer):
    class Meta(ESAddonSerializer.Meta):
        fields = ('id', 'icon_url', 'name', 'url')
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

    class Meta:
        model = Addon
        fields = ('id', 'current_version', 'default_locale',
                  'locale_disambiguation', 'name', 'target_locale', 'type',
                  'url', )
