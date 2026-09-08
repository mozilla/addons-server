from django.urls import re_path

from .views import developer_support


urlpatterns = [
    re_path(r'support/', developer_support, name='developer-support'),
]
