from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url(r'(?P<contribution_id>\d+)(?:/(?P<step>[\w-]+))?$',
        views.SupportWizard.as_view(), name='support'),
)
