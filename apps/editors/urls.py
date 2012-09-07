from django.conf.urls import url

from addons.urls import ADDON_ID
from . import views


# All URLs under /editors/
urlpatterns = (
    url(r'^$', views.home, name='editors.home'),
    url(r'^queue$', views.queue, name='editors.queue'),
    url(r'^queue/nominated$', views.queue_nominated,
        name='editors.queue_nominated'),
    url(r'^queue/pending$', views.queue_pending,
        name='editors.queue_pending'),
    url(r'^queue/preliminary$', views.queue_prelim,
        name='editors.queue_prelim'),
    url(r'^queue/fast$', views.queue_fast_track,
        name='editors.queue_fast_track'),
    url(r'^queue/reviews$', views.queue_moderated,
        name='editors.queue_moderated'),
    url(r'^queue/apps$', views.queue_apps,
        name='editors.queue_apps'),
    url(r'^queue/application_versions\.json$', views.application_versions_json,
        name='editors.application_versions_json'),
    url(r'^logs$', views.eventlog, name='editors.eventlog'),
    url(r'^log/(\d+)$', views.eventlog_detail, name='editors.eventlog.detail'),
    url(r'^reviewlog$', views.reviewlog, name='editors.reviewlog'),
    url(r'^queue_version_notes/%s?$' % ADDON_ID, views.queue_version_notes,
        name='editors.queue_version_notes'),
    url(r'^queue_viewing$', views.queue_viewing,
        name='editors.queue_viewing'),
    url(r'^review_viewing$', views.review_viewing,
        name='editors.review_viewing'),
    url(r'^review/%s$' % ADDON_ID, views.review, name='editors.review'),
    url(r'^apps/review/%s$' % ADDON_ID, views.app_review,
        name='editors.app_review'),
    url(r'^performance/(?P<user_id>\d+)?$', views.performance,
        name='editors.performance'),
    url(r'^motd$', views.motd, name='editors.motd'),
    url(r'^motd/save$', views.save_motd, name='editors.save_motd'),
    url(r'^abuse-reports/%s$' % ADDON_ID, views.abuse_reports,
        name='editors.abuse_reports'),
)
