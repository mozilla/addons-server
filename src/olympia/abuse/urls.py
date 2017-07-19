from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from views import AbuseViewSet


abusereports = SimpleRouter()
abusereports.register(r'report', AbuseViewSet, base_name='abusereport')

urlpatterns = [
    url(r'', include(abusereports.urls)),
]
