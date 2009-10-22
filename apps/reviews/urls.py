from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^display/(\d+)$', views.review_list, name='reviews.list'),
)
