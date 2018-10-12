from django.conf.urls import url
from django.shortcuts import redirect

from .views import module_admin


urlpatterns = [
    url('^modules$', module_admin, name='discovery.module_admin'),
    url('^.*', lambda request: redirect(
        'https://www.mozilla.org/firefox/new/', permanent=True)),
]
