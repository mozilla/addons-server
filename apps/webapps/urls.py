from django.conf.urls.defaults import include, patterns, url

from . import views
from addons import views as addons_views

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""


# These will all start with /app/<app_slug>/
detail_patterns = patterns('',
    url('^$', views.app_detail, name='apps.detail'),
    url('^more$', views.app_detail, name='apps.detail_more'),
    url('^share$', views.share, name='apps.share'),
    url('^abuse$', addons_views.report_abuse, name='apps.abuse')
)


urlpatterns = patterns('',
    url('^$', views.app_home, name='apps.home'),
    url('^search/$', 'search.views.app_search', name='apps.search'),
    url('^(?P<category>[^/]+)?$', views.app_list, name='apps.list'),

    # URLs for a single app.
    ('^app/%s/' % APP_SLUG, include(detail_patterns)),
)
