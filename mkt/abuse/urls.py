from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.abuse.resources import AppAbuseResource, UserAbuseResource

# Abuse API.
abuse = Api(api_name='abuse')
abuse.register(UserAbuseResource())
abuse.register(AppAbuseResource())

api_patterns = patterns('',
    url('^', include(abuse.urls)),
)
