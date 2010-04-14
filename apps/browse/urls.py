from django.conf.urls.defaults import patterns, url


from . import views


urlpatterns = patterns('',
    url('^language-tools$', views.language_tools,
        name='browse.language_tools'),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),

    url('^extensions/(?P<category>[^/]+)?/$', views.extensions,
        name='browse.extensions'),

    url('^extensions/(?P<category>[^/]+)/featured$',
        views.creatured, name='browse.creatured'),

    url('^personas/(?P<category>[^/]+)?$', views.personas,
        name='browse.personas'),
)
