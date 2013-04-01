from django.conf.urls import include, patterns, url

from tastypie.api import Api

from . import api

home = Api(api_name='home')
home.register(api.HomepageResource())
home.register(api.FeaturedHomeResource())

home_api_patterns = patterns('',
    url(r'^', include(home.urls)),
)
