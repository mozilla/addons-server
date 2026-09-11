from django.urls import re_path

from .views import developer_agreement_api, developer_support


urlpatterns = [
    re_path(r'support/', developer_support, name='developer-support'),
    re_path(r'agreement/', developer_agreement_api, name='developer-agreement'),
]
