from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.account.api import (AccountResource, InstalledResource, LoginResource,
                             NewsletterResource, PermissionResource)
from mkt.account.views import FeedbackView


# Account API.
account = Api(api_name='account')
account.register(AccountResource())
account.register(InstalledResource())
account.register(LoginResource())
account.register(PermissionResource())
account.register(NewsletterResource())

api_patterns = patterns('',
    url('^account/feedback/', FeedbackView.as_view(), name='account-feedback'),
    url('^', include(account.urls)),
)
