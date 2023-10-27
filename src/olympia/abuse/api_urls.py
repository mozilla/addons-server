from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from .views import (
    AddonAbuseViewSet,
    RatingAbuseViewSet,
    UserAbuseViewSet,
    cinder_webhook,
)


reporting = SimpleRouter()
reporting.register(r'addon', AddonAbuseViewSet, basename='abusereportaddon')
reporting.register(r'rating', RatingAbuseViewSet, basename='abusereportrating')
reporting.register(r'user', UserAbuseViewSet, basename='abusereportuser')

urlpatterns = [
    re_path(r'report/', include(reporting.urls)),
    re_path(r'response/', cinder_webhook, name='cinder-webhook'),
]
