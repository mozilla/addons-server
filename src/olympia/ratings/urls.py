from django.conf.urls import url

from olympia.amo.views import frontend_view


urlpatterns = [
    url(r'^$', frontend_view, name='addons.ratings.list'),
    url(r'^(?P<review_id>\d+)/$', frontend_view, name='addons.ratings.detail'),
]
