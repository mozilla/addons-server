from django.conf.urls import include, patterns, url

from rest_framework.routers import DefaultRouter

from mkt.comm.api import NoteViewSet, ThreadViewSet


api_thread = DefaultRouter()
api_thread.register(r'thread', ThreadViewSet, base_name='comm-thread')
api_thread.register(r'note', NoteViewSet, base_name='comm-note')

api_patterns = patterns('',
    url(r'^comm/', include(api_thread.urls))
)
