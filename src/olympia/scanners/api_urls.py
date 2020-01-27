from django.conf.urls import url

from .views import ScannerResultViewSet

urlpatterns = [
    url(r'^results/$', ScannerResultViewSet.as_view(), name='scanner-results'),
]
