from rest_framework import serializers

import amo
from addons.models import Category, Preview
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import find_language
from constants.applications import DEVICE_TYPES
from versions.models import Version

import mkt
from mkt.api.fields import ESTranslationSerializerField
from mkt.submit.serializers import SimplePreviewSerializer
from mkt.webapps.models import Geodata, Webapp
from mkt.webapps.utils import (
    dehydrate_content_ratings, dehydrate_descriptors, dehydrate_interactives,
    filter_content_ratings_by_region)
from mkt.webapps.api import AppSerializer, SimpleAppSerializer


class ESAppSerializer(AppSerializer):
    # Fields specific to search.
    absolute_url = serializers.SerializerMethodField('get_absolute_url')
    is_offline = serializers.BooleanField()
    reviewed = serializers.DateField()

    # Override previews, because we don't need the full PreviewSerializer.
    previews = SimplePreviewSerializer(many=True, source='all_previews')

    # Override those, because we want a different source. Also, related fields
    # will call self.queryset early if they are not read_only, so force that.
    categories = serializers.SlugRelatedField(read_only=True,
        many=True, slug_field='slug', source='all_categories')
    payment_account = serializers.HyperlinkedRelatedField(read_only=True,
        view_name='payment-account-detail', source='payment_account')
    manifest_url = serializers.CharField(source='manifest_url')

    # Override translations, because we want a different field.
    banner_message = ESTranslationSerializerField(
        source='geodata.banner_message')
    description = ESTranslationSerializerField()
    homepage = ESTranslationSerializerField()
    name = ESTranslationSerializerField()
    release_notes = ESTranslationSerializerField(
        source='current_version.releasenotes')
    support_email = ESTranslationSerializerField()
    support_url = ESTranslationSerializerField()

    class Meta(AppSerializer.Meta):
        fields = AppSerializer.Meta.fields + ['absolute_url', 'is_offline',
                                              'reviewed']

    def __init__(self, *args, **kwargs):
        super(ESAppSerializer, self).__init__(*args, **kwargs)

        # Remove fields that we don't have in ES or don't want / need to
        # support/support in search results at the moment.
        self.fields.pop('tags', None)
        self.fields.pop('upsold', None)

        # Set all fields as read_only just in case.
        for field_name in self.fields:
            self.fields[field_name].read_only = True

    @property
    def data(self):
        """
        Returns the serialized data on the serializer.
        """
        if self._data is None:
            if self.many:
                self._data = [self.to_native(item) for item in self.object]
            else:
                self._data = self.to_native(self.object)
        return self._data

    def field_to_native(self, obj, field_name):
        # DRF's field_to_native calls .all(), which we want to avoid, so we
        # provide a simplified version that doesn't and just iterates on the
        # object list.
        return [self.to_native(item) for item in obj.object_list]

    def to_native(self, obj):
        request = self.context['request']

        if request and request.method == 'GET' and 'lang' in request.GET:
            # We want to know if the user specifically requested a language,
            # in order to return only the relevant translations when that
            # happens.
            self.requested_language = find_language(request.GET['lang'].lower())

        app = self.create_fake_app(obj._source)
        return super(ESAppSerializer, self).to_native(app)

    def create_fake_app(self, data):
        """Create a fake instance of Webapp and related models from ES data."""
        is_packaged = data['app_type'] != amo.ADDON_WEBAPP_HOSTED
        is_privileged = data['app_type'] == amo.ADDON_WEBAPP_PRIVILEGED

        obj = Webapp(id=data['id'], app_slug=data['app_slug'],
                     is_packaged=is_packaged, type=amo.ADDON_WEBAPP,
                     icon_type='image/png')

        # Set relations and attributes we need on those relations.
        # The properties set on latest_version and current_version differ
        # because we are only setting what the serializer is going to need.
        # In particular, latest_version.is_privileged needs to be set because
        # it's used by obj.app_type_id.
        obj.listed_authors = []
        obj._current_version = Version()
        obj._current_version.addon = obj
        obj._current_version._developer_name = data['author']
        obj._current_version.supported_locales = data['supported_locales']
        obj._current_version.version = data['current_version']
        obj._latest_version = Version()
        obj._latest_version.is_privileged = is_privileged
        obj._geodata = Geodata()
        obj.all_categories = [Category(slug=cat) for cat in data['category']]
        obj.all_previews = [Preview(id=p['id'], modified=p['modified'],
            filetype=p['filetype']) for p in data['previews']]
        obj._device_types = [DEVICE_TYPES[d] for d in data['device']]

        # Set base attributes on the "fake" app using the data from ES.
        # It doesn't mean they'll get exposed in the serializer output, that
        # depends on what the fields/exclude attributes in Meta.
        for field_name in ('created', 'modified', 'default_locale',
                           'is_escalated', 'is_offline', 'manifest_url',
                           'premium_type', 'regions', 'reviewed', 'status',
                           'weekly_downloads'):
            setattr(obj, field_name, data.get(field_name))

        # Attach translations for all translated attributes.
        for field_name in ('name', 'description', 'homepage', 'support_email',
                           'support_url'):
            ESTranslationSerializerField.attach_translations(obj,
                data, field_name)
        ESTranslationSerializerField.attach_translations(obj._geodata,
            data, 'banner_message')
        ESTranslationSerializerField.attach_translations(obj._current_version,
            data, 'release_notes', target_name='releasenotes')

        # Set attributes that have a different name in ES.
        obj.public_stats = data['has_public_stats']

        # Avoid a query for payment_account if the app is not premium.
        if not obj.is_premium():
            obj.payment_account = None

        # Override obj.get_region() with a static list of regions generated
        # from the region_exclusions stored in ES.
        obj.get_regions = obj.get_regions(obj.get_region_ids(restofworld=True,
            excluded=data['region_exclusions']))

        # Some methods below will need the raw data from ES, put it on obj.
        obj.es_data = data

        return obj

    def get_content_ratings(self, obj):
        return filter_content_ratings_by_region({
            'ratings': dehydrate_content_ratings(
                obj.es_data.get('content_ratings', {})),
            'descriptors': dehydrate_descriptors(
                obj.es_data.get('content_descriptors', {})),
            'interactive_elements': dehydrate_interactives(
                obj.es_data.get('interactive_elements', [])),
            'regions': mkt.regions.REGION_TO_RATINGS_BODY()
        }, region=self.context['request'].REGION.slug)

    def get_versions(self, obj):
        return dict((v['version'], v['resource_uri'])
                    for v in obj.es_data['versions'])

    def get_ratings_aggregates(self, obj):
        return obj.es_data.get('ratings', {})

    def get_upsell(self, obj):
        upsell = obj.es_data.get('upsell', False)
        if upsell:
            region_id = self.context['request'].REGION.id
            exclusions = upsell.get('region_exclusions')
            if exclusions is not None and region_id not in exclusions:
                upsell['resource_uri'] = reverse('app-detail',
                    kwargs={'pk': upsell['id']})
            else:
                upsell = False
        return upsell

    def get_absolute_url(self, obj):
        return absolutify(obj.get_absolute_url())


class SimpleESAppSerializer(ESAppSerializer):

    class Meta(SimpleAppSerializer.Meta):
        pass


class SuggestionsESAppSerializer(ESAppSerializer):
    icon = serializers.SerializerMethodField('get_icon')

    class Meta(ESAppSerializer.Meta):
        fields = ['name', 'description', 'absolute_url', 'icon']

    def get_icon(self, app):
        return app.get_icon_url(64)


class RocketbarESAppSerializer(SuggestionsESAppSerializer):
    class Meta(ESAppSerializer.Meta):
        fields = ['name', 'icon', 'slug', 'manifest_url']
