from django.conf import settings
from django.conf.urls import url

from .views import ScannerResultView

urlpatterns = (
    [url(r'^results/$', ScannerResultView.as_view(), name='scanner-results')]
    if settings.INTERNAL_ROUTES_ALLOWED
    else []
)
