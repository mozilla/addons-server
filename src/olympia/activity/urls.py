from django.urls import re_path

from . import views


urlpatterns = [
    re_path(
        r'^attachment/(?P<log_id>\d+)',
        views.download_attachment,
        name='activity.attachment',
    )
]
