from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.index, name='firefoxcup.index'),
    url('^signup/', views.signup, name='firefoxcup.signup'),
)
