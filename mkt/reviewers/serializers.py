from rest_framework import serializers

from mkt.webapps.models import Webapp


class ReviewingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webapp
        fields = ('resource_uri', )

    resource_uri = serializers.HyperlinkedRelatedField(view_name='app-detail',
                                                       read_only=True,
                                                       source='*')
