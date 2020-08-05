from django.urls import path

from .views import AppVersionView

urlpatterns = [
    path('<str:application>/<str:version>/', AppVersionView.as_view(),
         name='appversions'),
]
