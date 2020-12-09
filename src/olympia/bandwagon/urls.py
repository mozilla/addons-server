from django.urls import re_path

from olympia.amo.views import frontend_view


urlpatterns = [
    re_path(
        r'^collections/(?P<user_id>[^/]+)/(?P<slug>[^/]+)/$',
        frontend_view,
        name='collections.detail',
    ),
    re_path(r'^collections/$', frontend_view, name='collections.list'),
]
