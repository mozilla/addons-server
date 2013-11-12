from mkt.webapps.api import AppSerializer, AppViewSet as BaseAppViewset


class FireplaceAppSerializer(AppSerializer):
    upsold = None
    tags = None
    class Meta(AppSerializer.Meta):
        exclude = AppSerializer.Meta.exclude + ['upsold', 'tags']

class AppViewSet(BaseAppViewset):

    serializer_class = FireplaceAppSerializer
