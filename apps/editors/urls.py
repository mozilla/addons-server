from django.conf.urls.defaults import patterns, url

from . import views

# All URLs under /editors/
urlpatterns = patterns('',
    url('^$', views.home, name='editors.home'),
)
