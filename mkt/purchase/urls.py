from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    # App purchase.
    url('^$', views.purchase, name='purchase'),
    url('^(?P<status>cancel|complete)$', views.purchase_done,
        name='purchase.done'),

    # TODO: Port these views.
    #url('^thanks/$', views.purchase_thanks, name='purchase.thanks'),
    #url('^error/$', views.purchase_error, name='purchase.error'),
)
