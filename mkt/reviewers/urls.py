from django.conf.urls.defaults import url

from mkt.urls import APP_SLUG
from . import views


# All URLs under /editortools/.
urlpatterns = (
    url(r'^$', views.home, name='reviewers.home'),
    url(r'^queue/apps$', views.queue_apps, name='reviewers.queue_apps'),
    url(r'^apps/review/%s$' % APP_SLUG, views.app_review,
        name='reviewers.app_review'),
)
