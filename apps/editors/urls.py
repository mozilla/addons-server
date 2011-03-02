from django.conf.urls.defaults import patterns, url

from . import views

# All URLs under /editors/
urlpatterns = patterns('',
    url(r'^queue$', views.queue, name='editors.queue'),
    url(r'^queue/nominated$', views.queue_nominated,
        name='editors.queue_nominated'),
    url(r'^queue/pending$', views.queue_pending,
        name='editors.queue_pending'),
    url(r'^queue/preliminary$', views.queue_prelim,
        name='editors.queue_prelim'),
    url(r'^queue/reviews$', views.queue_moderated,
        name='editors.queue_moderated'),
    url(r'^queue/application_versions\.json$', views.application_versions_json,
        name='editors.application_versions_json'),
    url(r'^logs$', views.eventlog, name='editors.eventlog'),
    url(r'^log/(\d+)$', views.eventlog_detail, name='editors.eventlog.detail'),
    url(r'^reviewlog$', views.reviewlog, name='editors.reviewlog'),
    url(r'^review/(?P<version_id>\d+)$', views.review, name='editors.review'),
    url(r'^motd$', views.motd, name='editors.motd'),
    url(r'^motd/save$', views.save_motd, name='editors.save_motd'),
    url(r'^$', views.home, name='editors.home'),
)
