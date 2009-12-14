from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^logout$', views.logout_view, name='users.logout'),
)
