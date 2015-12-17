from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.SearchView.as_view(), name='addons.api.search'),
    url(r'^(?P<slug>[^/]+)/$', views.DetailView.as_view(),
        name='addons.api.detail'),
]
