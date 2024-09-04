from django.urls import re_path

from . import views


urlpatterns = [
    re_path(r'^mail/', views.inbound_email, name='inbound-email-api'),
]

attachment_patterns = [
    re_path(
        r'^attachment/(?P<log_id>\d+)',
        views.download_attachment,
        name='activity.attachment',
    )
]
