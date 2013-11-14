from rest_framework import serializers

from mkt.api.base import CompatRelatedField
from mkt.webapps.models import Webapp


class ReviewingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webapp
        fields = ('resource_uri', )

    resource_uri = CompatRelatedField(
        view_name='api_dispatch_detail', read_only=True,
        tastypie={'resource_name': 'app',
                  'api_name': 'apps'},
        source='*')
