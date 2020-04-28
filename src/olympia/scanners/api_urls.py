from django.conf.urls import url

from .views import ScannerResultView

urlpatterns = [
    url(r'^results/$', ScannerResultView.as_view(), name='scanner-results')
]
