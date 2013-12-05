from django.conf.urls import include, patterns, url

from rest_framework.routers import DefaultRouter

from mkt.comm.api import NoteViewSet, post_email, ReplyViewSet, ThreadViewSet


api_thread = DefaultRouter()
api_thread.register(r'thread', ThreadViewSet, base_name='comm-thread')
api_thread.register(r'thread/(?P<thread_id>\d+)/note', NoteViewSet,
                    base_name='comm-note')
api_thread.register(
    r'thread/(?P<thread_id>\d+)/note/(?P<note_id>\d+)/replies', ReplyViewSet,
    base_name='comm-note-replies')

api_patterns = patterns('',
    url(r'^comm/', include(api_thread.urls)),
    url(r'^comm/email/', post_email, name='post-email-api')
)
