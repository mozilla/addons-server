from django.conf.urls.defaults import patterns, url, include

from . import views


# These all start with /addon/:id/reviews/:review_id/.
detail_patterns = patterns('',
    url('^$', views.review_list, name='reviews.detail'),
    url('^flag$', views.flag, name='reviews.flag'),
    url('^delete$', views.delete, name='reviews.delete'),
)

urlpatterns = patterns('',
    url('^$', views.review_list, name='reviews.list'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^user:(?P<user_id>\d+)$', views.review_list, name='reviews.user'),
)
