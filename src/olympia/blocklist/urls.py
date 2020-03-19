from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views


block = SimpleRouter()
block.register('block', views.BlockViewSet,
               basename='blocklist-block')

urlpatterns = [
    url(r'', include(block.urls)),
]
