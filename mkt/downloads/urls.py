from django.conf.urls import patterns, url

from mkt.downloads import views


urlpatterns = patterns('',
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url('^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file, name='downloads.file'),
    url('^blocked_packaged_app.zip$', views.blocked_packaged_app,
        name='downloads.blocked_packaged_app'),
)
