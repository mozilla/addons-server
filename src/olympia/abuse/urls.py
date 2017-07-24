from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from views import AddonAbuseViewSet, UserAbuseViewSet


abusereports = SimpleRouter()
abusereports.register(r'reportaddon', AddonAbuseViewSet,
                      base_name='abusereportaddon')
abusereports.register(r'reportuser', UserAbuseViewSet,
                      base_name='abusereportuser')

urlpatterns = [
    url(r'', include(abusereports.urls)),
]
