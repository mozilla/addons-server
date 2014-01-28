from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from mkt.fireplace.api import AppViewSet, ConsumerInfoView, FeaturedSearchView

apps = SimpleRouter()
apps.register(r'app', AppViewSet, base_name='fireplace-app')

urlpatterns = patterns('',
    url(r'^fireplace/', include(apps.urls)),
    url(r'^fireplace/consumer-info/',
        ConsumerInfoView.as_view(),
        name='fireplace-consumer-info'),
    url(r'^fireplace/search/featured/',
        FeaturedSearchView.as_view(),
        name='fireplace-featured-search-api'),
)
