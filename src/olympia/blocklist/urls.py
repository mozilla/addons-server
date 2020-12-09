from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from . import views


block = SimpleRouter()
block.register('block', views.BlockViewSet, basename='blocklist-block')

urlpatterns = [
    re_path(r'', include(block.urls)),
]
