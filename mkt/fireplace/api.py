import json

from django.http import HttpResponse
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny

from mkt.account.views import user_relevant_apps
from mkt.api.base import CORSMixin
from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.search.api import (FeaturedSearchView as BaseFeaturedSearchView,
                            SearchView as BaseSearchView)
from mkt.search.serializers import SimpleESAppSerializer
from mkt.webapps.api import SimpleAppSerializer, AppViewSet as BaseAppViewset


class FireplaceAppSerializer(SimpleAppSerializer):
    class Meta(SimpleAppSerializer.Meta):
        fields = ['author', 'banner_message', 'banner_regions', 'categories',
                  'content_ratings', 'current_version', 'description',
                  'device_types', 'homepage', 'icons', 'id', 'is_packaged',
                  'manifest_url', 'name', 'payment_required', 'premium_type',
                  'previews', 'price', 'price_locale', 'privacy_policy',
                  'public_stats', 'release_notes', 'ratings', 'slug', 'status',
                  'support_email', 'support_url', 'upsell', 'user']
        exclude = []


class FireplaceESAppSerializer(SimpleESAppSerializer):
    class Meta(SimpleESAppSerializer.Meta):
        fields = FireplaceAppSerializer.Meta.fields
        exclude = FireplaceAppSerializer.Meta.exclude

    def get_user_info(self, app):
        # Fireplace search should always be anonymous for extra-cacheability.
        return None


class AppViewSet(BaseAppViewset):
    serializer_class = FireplaceAppSerializer


class FeaturedSearchView(BaseFeaturedSearchView):
    serializer_class = FireplaceESAppSerializer
    authentication_classes = []


class SearchView(BaseSearchView):
    serializer_class = FireplaceESAppSerializer


class ConsumerInfoView(CORSMixin, RetrieveAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    cors_allowed_methods = ['get']
    permission_classes = (AllowAny,)

    def retrieve(self, request, *args, **kwargs):
        data = {
            'region': request.REGION.slug
        }
        if request.amo_user:
          data['apps'] = user_relevant_apps(request.amo_user)

        # Return an HttpResponse directly to be as fast as possible.
        return HttpResponse(json.dumps(data),
                            content_type='application/json; charset=utf-8')
