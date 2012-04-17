from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    # App purchase.
    url('^$', views.purchase, name='purchase'),
    url('^preapproval$', views.preapproval,
        name='detail.purchase.preapproval'),
    url('^(?P<status>cancel|complete)$', views.purchase_done,
        name='purchase.done'),
    url('^reissue$', views.reissue, name='purchase.reissue'),

    # TODO: Port these views.
    #url('^thanks/$', views.purchase_thanks, name='purchase.thanks'),
    #url('^error/$', views.purchase_error, name='purchase.error'),
)
