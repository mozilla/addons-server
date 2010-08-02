from django.conf.urls.defaults import patterns, url
from . import views
import search.views as search_views



urlpatterns = patterns('',
    url('^tags/top$', views.top_cloud, name='tags.top_cloud'),
    url('^tag/(?P<tag_name>[^/]+)$', search_views.search, name='tags.detail'),
)
