from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
	 url('^ecosystem$', views.ecosystem, name='mkt.zadmin.ecosystem')
)
