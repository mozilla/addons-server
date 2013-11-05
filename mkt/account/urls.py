from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.account.api import (AccountResource, InstalledResource, LoginResource,
                             PermissionResource)
from mkt.account.views import FeedbackView, NewsletterView


# Account API (old tastypie resources).
account = Api(api_name='account')
account.register(AccountResource())
account.register(InstalledResource())
account.register(LoginResource())
account.register(PermissionResource())

# Account API (new DRF views).
drf_patterns = patterns('',
    url('^newsletter/', NewsletterView.as_view(), name='account-newsletter'),
    url('^feedback/', FeedbackView.as_view(), name='account-feedback'),
)

api_patterns = patterns('',
    url('^account/', include(drf_patterns)),
    url('^', include(account.urls)),
)
