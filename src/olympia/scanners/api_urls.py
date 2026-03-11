from django.urls import re_path

from .views import patch_scanner_result, push_scanner_result


urlpatterns = [
    re_path(r'^results/$', push_scanner_result, name='scanner-result-push'),
    re_path(
        r'^results/(?P<pk>\d+)/$',
        patch_scanner_result,
        name='scanner-result-patch',
    ),
]
