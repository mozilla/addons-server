from django.conf.urls import patterns, url

from search.views import search
from . import views


urlpatterns = patterns('',
    url('^tags/top$', views.top_cloud, name='tags.top_cloud'),
    url('^tag/(?P<tag_name>[^/]+)$', search, name='tags.detail'),
)
