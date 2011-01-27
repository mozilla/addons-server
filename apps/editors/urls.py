from django.conf.urls.defaults import patterns, url

from . import views

# All URLs under /editors/
urlpatterns = patterns('',
    url(r'^queue$', views.queue, name='editors.queue'),
    url(r'^queue/pending$', views.queue_pending,
        name='editors.queue_pending'),
    url(r'^logs$', views.eventlog, name='editors.eventlog'),
    url(r'^log/(\d+)$', views.eventlog_detail, name='editors.eventlog.detail'),

    url(r'^review/(?P<version_id>\d+)$', views.review, name='editors.review'),
    url(r'^$', views.home, name='editors.home'),
)
