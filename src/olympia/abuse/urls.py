from django.urls import re_path, include

from rest_framework.routers import SimpleRouter
from .views import AddonAbuseViewSet, UserAbuseViewSet


reporting = SimpleRouter()
reporting.register(r'addon', AddonAbuseViewSet,
                   basename='abusereportaddon')
reporting.register(r'user', UserAbuseViewSet,
                   basename='abusereportuser')

urlpatterns = [
    re_path(r'report/', include(reporting.urls)),
]
