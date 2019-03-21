from django.conf.urls import url

from olympia.amo.views import frontend_view

urlpatterns = [
    url(r'^collections/(?P<user_id>[^/]+)/(?P<slug>[^/]+)/$', frontend_view,
        name='collections.detail'),
    url(r'^collections/$', frontend_view, name='collections.list'),
]
