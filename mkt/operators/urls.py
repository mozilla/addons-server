from django.conf.urls import patterns, url

from . import views


url_patterns = patterns('',
    url(r'^preloads/$', views.preloads, name='operators.preloads'),
)
