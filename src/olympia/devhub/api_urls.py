from django.urls import re_path

from .views import DeveloperAgreementView, developer_support


urlpatterns = [
    re_path(r'support/', developer_support, name='developer-support'),
    re_path(
        r'agreement/', DeveloperAgreementView.as_view(), name='developer-agreement'
    ),
]
