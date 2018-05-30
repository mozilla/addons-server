from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from .views import AddonAbuseViewSet, UserAbuseViewSet


reporting = SimpleRouter()
reporting.register(r'addon', AddonAbuseViewSet,
                   base_name='abusereportaddon')
reporting.register(r'user', UserAbuseViewSet,
                   base_name='abusereportuser')

urlpatterns = [
    url(r'report/', include(reporting.urls)),
]
