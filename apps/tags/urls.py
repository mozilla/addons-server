from django.conf import settings
from django.conf.urls.defaults import patterns, url

from search.views import app_search, search
from . import views


urlpatterns = patterns('',
    url('^tags/top$', views.top_cloud, name='tags.top_cloud'),
    url('^tag/(?P<tag_name>[^/]+)$',
        app_search if settings.APP_PREVIEW else search, name='tags.detail'),
)
