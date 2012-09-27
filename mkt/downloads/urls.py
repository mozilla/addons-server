from django.conf.urls import patterns, url

from mkt.downloads import views


urlpatterns = patterns('',
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url('^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file, name='downloads.file'),
)
