from rest_framework import serializers

from olympia.addons.models import Addon, attach_tags
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.api.fields import TranslationSerializerField
from olympia.api.serializers import BaseESSerializer
from olympia.files.models import File
from olympia.versions.models import Version


class FileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    platform = serializers.ReadOnlyField(source='get_platform_display')
    status = serializers.ReadOnlyField(source='get_status_display')

    class Meta:
        model = File
        fields = ('id', 'created', 'hash', 'platform', 'size', 'status', 'url')

    def get_url(self, obj):
        # File.get_url_path() is a little different, it's already absolute, but
        # needs a src parameter that is appended as a query string.
        return obj.get_url_path(src='')


class VersionSerializer(serializers.ModelSerializer):
    edit_url = serializers.SerializerMethodField()
    files = FileSerializer(source='all_files', many=True)
    url = serializers.SerializerMethodField()

    # FIXME:
    # - license
    # - appversion compatibility info
    # - release notes (separate endpoint ?)
    # - all the reviewer/admin fields (different serializer/endpoint)

    class Meta:
        model = Version
        fields = ('id', 'edit_url', 'files', 'reviewed', 'url', 'version')

    def get_url(self, obj):
        return absolutify(obj.get_url_path())

    def get_edit_url(self, obj):
        return absolutify(obj.addon.get_dev_url(
            'versions.edit', args=[obj.pk], prefix_only=True))


class AddonSerializer(serializers.ModelSerializer):
    current_version = VersionSerializer()
    description = TranslationSerializerField()
    edit_url = serializers.SerializerMethodField()
    homepage = TranslationSerializerField()
    name = TranslationSerializerField()
    review_url = serializers.SerializerMethodField()
    status = serializers.ReadOnlyField(source='get_status_display')
    summary = TranslationSerializerField()
    support_email = TranslationSerializerField()
    support_url = TranslationSerializerField()
    tags = serializers.SerializerMethodField()
    type = serializers.ReadOnlyField(source='get_type_display')
    url = serializers.SerializerMethodField()

    # FIXME:
    # - categories (need to sort out the id/slug mess in existing search code)
    # - icon/previews
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
                  'edit_url', 'guid', 'homepage', 'is_listed', 'name',
                  'last_updated', 'public_stats', 'review_url', 'slug',
                  'status', 'summary', 'support_email', 'support_url', 'tags',
                  'type', 'url')

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


class ESAddonSerializer(BaseESSerializer, AddonSerializer):
    datetime_fields = ('last_updated',)
    translated_fields = ('name', 'description', 'homepage', 'summary',
                         'support_email', 'support_url')

    def fake_object(self, data):
        """Create a fake instance of Addon and related models from ES data."""
        obj = Addon(id=data['id'], slug=data['slug'], is_listed=True)

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
                    size=file_['size'], status=file_['status'],
                    version=obj._current_version)
                for file_ in data_files
            ]

        # Attach base attributes that have the same name/format in ES and in
        # the model.
        self._attach_fields(
            obj, data,
            ('average_daily_users', 'bayesian_rating', 'created',
             'default_locale', 'guid', 'hotness', 'is_listed', 'last_updated',
             'public_stats', 'slug', 'status', 'type', 'weekly_downloads'))

        # Attach attributes that do not have the same name/format in ES.
        obj.tag_list = data['tags']
        obj.disabled_by_user = data['is_disabled']  # Not accurate, but enough.

        # Attach translations (they require special treatment).
        self._attach_translations(obj, data, self.translated_fields)

        return obj
