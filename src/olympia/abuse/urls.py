from django.urls import path

from olympia.abuse.views import appeal


urlpatterns = [
    path('appeal/<str:decision_id>/', appeal, name='abuse.appeal'),
]
