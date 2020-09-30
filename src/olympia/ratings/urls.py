from django.urls import re_path

from olympia.amo.views import frontend_view


urlpatterns = [
    re_path(r'^$', frontend_view, name='addons.ratings.list'),
    re_path(r'^(?P<review_id>\d+)/$', frontend_view, name='addons.ratings.detail'),
]
