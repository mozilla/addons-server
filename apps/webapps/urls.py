from django.conf.urls.defaults import include, url

from . import views


urlpatterns = (
    url(r'(?P<app_slug>[^/<>"\']+)/$', views.app_detail, name='apps.detail'),
)
