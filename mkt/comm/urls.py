from django.conf.urls import include, patterns, url

from rest_framework.routers import DefaultRouter

from mkt.comm.api import (AttachmentViewSet, NoteViewSet, post_email,
                          ReplyViewSet, ThreadViewSet)


api_thread = DefaultRouter()
api_thread.register(r'thread', ThreadViewSet, base_name='comm-thread')
api_thread.register(r'thread/(?P<thread_id>\d+)/note', NoteViewSet,
                    base_name='comm-note')
api_thread.register(
    r'thread/(?P<thread_id>\d+)/note/(?P<note_id>\d+)/replies', ReplyViewSet,
    base_name='comm-note-replies')
api_thread.register(
    r'note/(?P<note_id>\d+)/attachment',
    AttachmentViewSet, base_name='comm-attachment')

api_patterns = patterns('',
    url(r'^comm/', include(api_thread.urls)),
    url(r'^comm/email/', post_email, name='post-email-api')
)
