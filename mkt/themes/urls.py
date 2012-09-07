from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url('^$', views.detail, name='themes.detail'),
)

theme_patterns = patterns('',
    url('^(?P<category>[^ /]+)?$', views.browse_themes, name='themes.browse')
)
