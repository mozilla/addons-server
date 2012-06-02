from django.conf.urls.defaults import include, patterns, url

import waffle

import addons.views
from mkt.ratings.urls import review_patterns
from . import views


urlpatterns = patterns('',
    url('^$', views.detail, name='detail'),
    url('^abuse$', views.abuse, name='detail.abuse'),
    url('^abuse/recaptcha$', views.abuse_recaptcha,
        name='detail.abuse.recaptcha'),
    url('^record$',
        (views.record_anon
         if waffle.switch_is_active('anonymous-free-installs')
         else views.record),
        name='detail.record'),
    url('^privacy$', views.privacy, name='detail.privacy'),

    ('^purchase/', include('mkt.purchase.urls')),

    # Statistics.
    ('^statistics/', include('mkt.stats.urls')),

    # Ratings.
    ('^reviews/', include(review_patterns)),

    # TODO: Port abuse.
    url('^abuse$', addons.views.report_abuse, name='detail.abuse'),
)
