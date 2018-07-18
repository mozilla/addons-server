from django.conf.urls import url

from . import views


urlpatterns = (
    url('^incoming/?$', views.incoming, name='compat.incoming'),
    url('^reporter/?$', views.reporter, name='compat.reporter'),
    url(
        '^reporter/(.+)$', views.reporter_detail, name='compat.reporter_detail'
    ),
)
