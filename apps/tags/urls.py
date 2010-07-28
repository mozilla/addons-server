from django.conf.urls.defaults import patterns, url
from . import views

urlpatterns = patterns('',
    url('^tags/top$', views.top_cloud, name='tags.top_cloud'),
)
