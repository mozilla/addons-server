from django.conf.urls.defaults import include, patterns, url
from django.shortcuts import redirect

from . import views
from addons import views as addons_views
from reviews.urls import review_patterns

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""


# These will all start with /app/<app_slug>/
detail_patterns = patterns('',
    url('^$', addons_views.addon_detail, name='apps.detail'),
    url('^more$', addons_views.addon_detail, name='apps.detail_more'),
    url('^share$', views.share, name='apps.share'),
    url('^abuse$', addons_views.report_abuse, name='apps.abuse'),
    url('^record$', views.record, name='apps.record'),
    url('^contribute/$', addons_views.contribute, name='apps.contribute'),
    url('^contribute/(?P<status>cancel|complete)$', addons_views.paypal_result,
        name='apps.paypal'),

    # TODO(andym): generate these instead of copying them around.
    url('^purchase/$', addons_views.purchase, name='apps.purchase'),
    url(r'purchase/start$', addons_views.paypal_start,
        name='apps.purchase.start'),
    url('^purchase/error/$', addons_views.purchase_error,
        name='apps.purchase.error'),
    url('^purchase/thanks/$', addons_views.purchase_thanks,
        name='apps.purchase.thanks'),
    url('^purchase/(?P<status>cancel|complete)$',
        addons_views.purchase_complete, name='apps.purchase.finished'),

    ('^reviews/', include(review_patterns('apps'))),
)


urlpatterns = patterns('',
    url('^$', views.app_home, name='apps.home'),
    url('^search/$', 'search.views.app_search', name='apps.search'),

    # Review spam.
    url('^reviews/spam/$', 'reviews.views.spam', name='apps.reviews.spam'),

    url('^apps/(?P<category>[^/]+)?$', views.app_list, name='apps.list'),

    # URLs for a single app.
    ('^app/%s/' % APP_SLUG, include(detail_patterns)),
)
