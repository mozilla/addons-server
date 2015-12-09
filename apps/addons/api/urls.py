from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^search/$', views.SearchView.as_view(), name='addons.api.search'),
]
