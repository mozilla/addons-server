from django.urls import path

from olympia.abuse.views import appeal


urlpatterns = [
    path(
        'appeal/<str:decision_cinder_id>/',
        appeal,
        kwargs={'abuse_report_id': None},
        name='abuse.appeal_author',
    ),
    path(
        'appeal/<str:abuse_report_id>/<str:decision_cinder_id>/',
        appeal,
        name='abuse.appeal_reporter',
    ),
]
