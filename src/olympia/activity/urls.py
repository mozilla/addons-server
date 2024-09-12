from django.urls import include, re_path

from . import views


urlpatterns = [
    re_path(r'', include('olympia.activity.api_urls')),
    re_path(r'^mail/', views.inbound_email, name='inbound-email-api'),
]
