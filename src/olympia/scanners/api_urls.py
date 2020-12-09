from django.conf import settings
from django.urls import re_path

from .views import ScannerResultView


urlpatterns = (
    [re_path(r'^results/$', ScannerResultView.as_view(), name='scanner-results')]
    if settings.INTERNAL_ROUTES_ALLOWED
    else []
)
