from django.conf import settings
from django.urls import re_path

from .views import ScannerResultView, patch_scanner_result


urlpatterns = [
    re_path(
        r'^results/(?P<pk>\d+)/$',
        patch_scanner_result,
        name='scanner-result-patch',
    ),
]

if settings.INTERNAL_ROUTES_ALLOWED:
    urlpatterns.append(
        re_path(r'^results/$', ScannerResultView.as_view(), name='scanner-results')
    )
