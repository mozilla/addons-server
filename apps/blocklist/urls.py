from django.conf.urls import patterns, url

from . import views

urlpatterns = patterns('',
  url('^$', views.blocked_list, name='blocked.list'),
  # The prefix tells us to look at item, plugin, or gfx.
  url('^([ip]\d+)$', views.blocked_detail, name='blocked.detail'),
)
