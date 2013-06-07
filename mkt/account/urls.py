from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.account.api import (AccountResource, FeedbackResource,
                             InstalledResource, LoginResource,
                             NewsletterResource, PermissionResource)


# Account API.
account = Api(api_name='account')
account.register(AccountResource())
account.register(FeedbackResource())
account.register(InstalledResource())
account.register(LoginResource())
account.register(PermissionResource())
account.register(NewsletterResource())

api_patterns = patterns('',
    url('^', include(account.urls)),
)
