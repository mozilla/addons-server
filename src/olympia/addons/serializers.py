from rest_framework import serializers

from olympia import amo
from olympia.addons.models import Addon, attach_tags, Persona
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.api.fields import ReverseChoiceField, TranslationSerializerField
from olympia.api.serializers import BaseESSerializer
from olympia.applications.models import AppVersion
from olympia.constants.applications import APPS_ALL
from olympia.files.models import File
from olympia.versions.models import ApplicationsVersions, Version


class FileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    platform = ReverseChoiceField(choices=amo.PLATFORM_CHOICES_API.items())
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())

    class Meta:
        model = File
        fields = ('id', 'created', 'hash', 'platform', 'size', 'status', 'url')

    def get_url(self, obj):
        # File.get_url_path() is a little different, it's already absolute, but
        # needs a src parameter that is appended as a query string.
        return obj.get_url_path(src='')


class VersionSerializer(serializers.ModelSerializer):
    compatibility = serializers.SerializerMethodField()
    edit_url = serializers.SerializerMethodField()
    files = FileSerializer(source='all_files', many=True)
    url = serializers.SerializerMethodField()

    # FIXME:
    # - license
    # - release notes (separate endpoint ?)
    # - all the reviewer/admin fields (different serializer/endpoint)

    class Meta:
        model = Version
        fields = ('id', 'compatibility', 'edit_url', 'files', 'reviewed',
                  'url', 'version')

    def get_url(self, obj):
        return absolutify(obj.get_url_path())

    def get_edit_url(self, obj):
        return absolutify(obj.addon.get_dev_url(
            'versions.edit', args=[obj.pk], prefix_only=True))

    def get_compatibility(self, obj):
        return {app.short: {'min': compat.min.version,
                            'max': compat.max.version}
                for app, compat in obj.compatible_apps.items()}


class AddonSerializer(serializers.ModelSerializer):
    current_version = VersionSerializer()
    description = TranslationSerializerField()
    edit_url = serializers.SerializerMethodField()
    homepage = TranslationSerializerField()
    icon_url = serializers.SerializerMethodField()
    name = TranslationSerializerField()
    review_url = serializers.SerializerMethodField()
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())
    summary = TranslationSerializerField()
    support_email = TranslationSerializerField()
    support_url = TranslationSerializerField()
    tags = serializers.SerializerMethodField()
    theme_data = serializers.SerializerMethodField()
    type = ReverseChoiceField(choices=amo.ADDON_TYPE_CHOICES_API.items())
    url = serializers.SerializerMethodField()

    # FIXME:
    # - categories (need to sort out the id/slug mess in existing search code)
    # - previews
    # - average rating, number of downloads, hotness
    # - dictionary-specific things
    # - persona-specific things
    # - contributions-related things
    # - annoying/thankyou and related fields
    # - authors
    # - dependencies, site_specific, external_software
    # - thereason/thefuture (different endpoint ?)
    # - in collections, other add-ons by author, eula, privacy policy
    # - eula / privacy policy (different endpoint)
    # - all the reviewer/admin-specific fields (different serializer/endpoint)

    class Meta:
        model = Addon
        fields = ('id', 'current_version', 'default_locale', 'description',
                  'edit_url', 'guid', 'homepage', 'icon_url', 'is_listed',
                  'name', 'last_updated', 'public_stats', 'review_url', 'slug',
                  'status', 'summary', 'support_email', 'support_url', 'tags',
                  'theme_data', 'type', 'url')

    def to_representation(self, obj):
        data = super(AddonSerializer, self).to_representation(obj)
        if data['theme_data'] is None:
            data.pop('theme_data')
        return data

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

    def get_theme_data(self, obj):
        theme_data = None

        if obj.type == amo.ADDON_PERSONA and not self.is_broken_persona(obj):
            theme_data = obj.persona.theme_data
        return theme_data

    def is_broken_persona(self, obj):
        """Find out if the object is a Persona and either is missing its
        Persona instance or has a broken one.

        Call this everytime something in the serializer is suceptible to call
        something on the Persona instance, explicitely or not, to avoid 500
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


class ESAddonSerializer(BaseESSerializer, AddonSerializer):
    datetime_fields = ('created', 'last_updated', 'modified')
    translated_fields = ('name', 'description', 'homepage', 'summary',
                         'support_email', 'support_url')

    def fake_object(self, data):
        """Create a fake instance of Addon and related models from ES data."""
        obj = Addon(id=data['id'], slug=data['slug'], is_listed=True)

        # Attach base attributes that have the same name/format in ES and in
        # the model.
        self._attach_fields(
            obj, data,
            ('average_daily_users', 'bayesian_rating', 'created',
             'default_locale', 'guid', 'hotness', 'icon_type', 'is_listed',
             'last_updated', 'modified', 'public_stats', 'slug', 'status',
             'type', 'weekly_downloads'))

        # Temporary hack to make sure all add-ons have a modified date when
        # serializing, to avoid errors when calling get_icon_url().
        # Remove once all add-ons have been reindexed at least once since the
        # addition of `modified` in the mapping.
        if obj.modified is None:
            obj.modified = obj.created

        # Attach attributes that do not have the same name/format in ES.
        obj.tag_list = data['tags']
        obj.disabled_by_user = data['is_disabled']  # Not accurate, but enough.

        # Categories are annoying, skip them for now. We probably need to start
        # declaring them in the code to properly handle translations etc if we
        # want to display them in search results.
        obj.all_categories = []

        # Attach translations (they require special treatment).
        self._attach_translations(obj, data, self.translated_fields)

        # Attach related models (also faking them).
        data_version = data.get('current_version')
        if data_version:
            obj._current_version = Version(
                addon=obj, id=data_version['id'],
                reviewed=self.handle_date(data_version['reviewed']),
                version=data_version['version'])
            data_files = data_version.get('files', [])
            obj._current_version.all_files = [
                File(
                    id=file_['id'], created=self.handle_date(file_['created']),
                    hash=file_['hash'], filename=file_['filename'],
                    platform=file_['platform'], size=file_['size'],
                    status=file_['status'], version=obj._current_version)
                for file_ in data_files
            ]

            # In ES we store integers for the appversion info, we need to
            # convert it back to strings.
            compatible_apps = {}
            for app_id, compat_dict in data['appversion'].items():
                app_name = APPS_ALL[int(app_id)]
                compatible_apps[app_name] = ApplicationsVersions(
                    min=AppVersion(version=compat_dict.get('min_human', '')),
                    max=AppVersion(version=compat_dict.get('max_human', '')))

            obj._current_version.compatible_apps = compatible_apps

        if data['type'] == amo.ADDON_PERSONA:
            persona_data = data.get('persona')
            if persona_data:
                obj.persona = Persona(
                    addon=obj,
                    accentcolor=persona_data['accentcolor'],
                    display_username=persona_data['author'],
                    header=persona_data['header'],
                    footer=persona_data['footer'],
                    persona_id=1 if persona_data['is_new'] else None,
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
