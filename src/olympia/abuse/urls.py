from django.urls import path

from olympia.abuse.views import appeal


urlpatterns = [
    path(
        'appeal/<str:abuse_report_id>/<str:decision_id>/', appeal, name='abuse.appeal'
    ),
]
