from django.conf.urls.defaults import patterns, url, include

from . import views

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    url('^edit$', views.addons_edit,
        name='devhub.addons.edit'),
)

urlpatterns = patterns('',
    url('^$', views.index, name='devhub.index'),

    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),

    url('^addons$', views.addons_dashboard, name='devhub.addons'),
    url('^addons/activity$', views.addons_activity,
        name='devhub.addons.activity'),
    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/([^/]+)$', views.upload_detail,
        name='devhub.upload_detail'),
)
