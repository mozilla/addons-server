from mkt.search.api import FeaturedSearchView as BaseFeaturedSearchView
from mkt.search.serializers import SimpleESAppSerializer
from mkt.webapps.api import SimpleAppSerializer, AppViewSet as BaseAppViewset


class FireplaceAppSerializer(SimpleAppSerializer):
    class Meta(SimpleAppSerializer.Meta):
        fields = ['author', 'banner_message', 'banner_regions', 'categories',
                  'content_ratings', 'current_version', 'description',
                  'device_types', 'homepage', 'icons', 'id', 'is_packaged',
                  'manifest_url', 'name', 'payment_required', 'premium_type',
                  'previews', 'price', 'price_locale', 'public_stats',
                  'release_notes', 'ratings', 'slug', 'status',
                  'support_email', 'support_url', 'upsell', 'user']
        exclude = []


class FireplaceESAppSerializer(SimpleESAppSerializer):
    class Meta(SimpleESAppSerializer.Meta):
        fields = FireplaceAppSerializer.Meta.fields
        exclude = FireplaceAppSerializer.Meta.exclude


class AppViewSet(BaseAppViewset):
    serializer_class = FireplaceAppSerializer


class FeaturedSearchView(BaseFeaturedSearchView):
    serializer_class = FireplaceESAppSerializer
