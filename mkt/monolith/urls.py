from django.conf.urls import patterns, url

from .resources import MonolithView


urlpatterns = patterns('',
    url(r'^monolith/data/', MonolithView.as_view(), name='monolith-list'),
)
