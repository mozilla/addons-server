from django.conf.urls import url

from olympia.github.views import GithubView


urlpatterns = [
    url(r'^validate/$', GithubView.as_view(), name='github.validate')
]
