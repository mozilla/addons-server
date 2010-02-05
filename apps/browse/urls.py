from django.conf.urls.defaults import patterns, url


from . import views


urlpatterns = patterns('',
    url('^language-tools$', views.language_tools,
        name='browse.language_tools'),
)
