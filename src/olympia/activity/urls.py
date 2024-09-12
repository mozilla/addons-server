from django.urls import re_path, include

from . import views

urlpatterns = [
    re_path(r'', include('olympia.activity.api_urls')),
    re_path(r'^mail/', views.inbound_email, name='inbound-email-api'),
]