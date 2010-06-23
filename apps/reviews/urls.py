from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.review_list, name='reviews.list'),
    url('^(?P<review_id>\d+)$', views.review_list, name='reviews.detail'),
    url('^user:(?P<user_id>\d+)$', views.review_list, name='reviews.user'),
)
