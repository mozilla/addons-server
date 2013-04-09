from django.conf import settings
from django.conf.urls import include, patterns, url

from tastypie.api import Api
from tastypie_services.services import (ErrorResource, SettingsResource)
from mkt.api.base import handle_500
from mkt.api.resources import (AppResource, CategoryResource, PreviewResource,
                               StatusResource, ValidationResource)
from mkt.ratings.resources import RatingResource
from mkt.search.api import SearchResource, WithCreaturedResource


api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(PreviewResource())
api.register(WithCreaturedResource())
api.register(SearchResource())
api.register(StatusResource())
api.register(RatingResource())


urls = [url(r'^', include(api.urls)),]
if settings.ALLOW_TASTYPIE_SERVICES:
    services = Api(api_name='services')
    services.register(ErrorResource(set_handler=handle_500))
    if getattr(settings, 'CLEANSED_SETTINGS_ACCESS', False):
        services.register(SettingsResource())

    urls.append(url(r'^', include(services.urls)))

urlpatterns = patterns('', *urls)
