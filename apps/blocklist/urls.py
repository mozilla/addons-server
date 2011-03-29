from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
  url('^$', views.blocked_list, name='blocked.list'),
  # The prefix tells us to look at item, plugin, or gfx.
  url('^([ipg]\d+)$', views.blocked_detail, name='blocked.detail'),
)
