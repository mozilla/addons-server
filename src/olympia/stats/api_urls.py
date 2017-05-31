from django.conf.urls import url

from . import views


urlpatterns = [
    # Archived stats
    url('^archive/(?P<slug>[^/]+)/(?P<year>\d{4})/(?P<month>\d{2})/$',
        views.ArchiveListView.as_view(),
        name='stats.archive_list'),
    url('^archive/(?P<slug>[^/]+)/'
        '(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{1,2})/'
        '(?P<model_name>\w+)/$',
        views.ArchiveView.as_view(),
        name='stats.archive'),
]
