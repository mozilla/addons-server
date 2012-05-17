from django.conf.urls.defaults import include, patterns, url

import addons.views
from . import views

urlpatterns = patterns('',
    url('^$', views.detail, name='themes.detail'),
)
