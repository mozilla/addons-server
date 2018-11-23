from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from .views import AddonAbuseViewSet, UserAbuseViewSet


reporting = SimpleRouter()
reporting.register(r'addon', AddonAbuseViewSet,
                   basename='abusereportaddon')
reporting.register(r'user', UserAbuseViewSet,
                   basename='abusereportuser')

urlpatterns = [
    url(r'report/', include(reporting.urls)),
]
