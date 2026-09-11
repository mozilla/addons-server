from django.urls import re_path

from . import views


urlpatterns = [
    re_path(r'^mail/', views.inbound_email, name='inbound-email-api'),
]

activity_v5 = urlpatterns + [
    re_path(r'^$', views.ActivityView.as_view(), name='developer-activity'),
]
