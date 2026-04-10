from django.urls import re_path

from . import views


urlpatterns = [
    re_path(
        r'^attachment/(?P<activity_log_id>\d+)',
        views.download_attachment,
        name='activity.attachment',
    )
]
