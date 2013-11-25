from mkt.webapps.api import AppSerializer, AppViewSet as BaseAppViewset


class FireplaceAppSerializer(AppSerializer):
    upsold = None
    tags = None
    class Meta(AppSerializer.Meta):
        exclude = AppSerializer.Meta.exclude + [
            'absolute_url', 'app_type', 'categories', 'created',
            'default_locale', 'payment_account' 'regions',
            'supported_locales', 'weekly_downloads', 'upsold', 'tags',]

class AppViewSet(BaseAppViewset):

    serializer_class = FireplaceAppSerializer
