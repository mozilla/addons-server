from mkt.webapps.api import SimpleAppSerializer, AppViewSet as BaseAppViewset


class FireplaceAppSerializer(SimpleAppSerializer):
    pass


class AppViewSet(BaseAppViewset):
    serializer_class = FireplaceAppSerializer
