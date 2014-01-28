import json

from django.http import HttpResponse
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny

import amo

from mkt.api.base import CORSMixin
from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
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
            user = request.amo_user
            # FIXME: values_list() doesn't appear to be cached by cachemachine,
            # is that going to be a problem ?
            data['developed'] = list(user.addonuser_set.filter(
                role=amo.AUTHOR_ROLE_OWNER).values_list('addon_id', flat=True))
            data['installed'] = list(user.installed_set.values_list('addon_id',
                flat=True))
            data['purchased'] = list(user.purchase_ids())

        # Return an HttpResponse directly to be as fast as possible.
        return HttpResponse(json.dumps(data),
                            content_type='application/json; charset=utf-8')
