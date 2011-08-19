from django.conf.urls.defaults import url

from . import views


urlpatterns = (
    url(r'^search/$', 'search.views.app_search', name='apps.search'),
    url(r'^(?P<app_slug>[^/<>"\']+)/$', views.app_detail, name='apps.detail'),
    url(r'^(?P<app_slug>[^/<>"\']+)/more$', views.app_detail,
        name='apps.detail_more'),
)
