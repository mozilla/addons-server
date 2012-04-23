from django.conf.urls.defaults import url

from mkt.urls import APP_SLUG
from . import views


# All URLs under /reviewers/.
urlpatterns = (
    url(r'^$', views.home, name='reviewers.home'),
    url(r'^apps/queue/$', views.queue_apps,
        name='reviewers.apps.queue_pending'),
    url(r'^apps/review/%s$' % APP_SLUG, views.app_review,
        name='reviewers.apps.review'),
    url(r'^apps/logs$', views.logs, name='reviewers.apps.logs'),
    url(r'^apps/motd$', views.motd, name='reviewers.apps.motd'),
)
