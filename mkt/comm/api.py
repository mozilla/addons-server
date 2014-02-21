import os

from django.conf import settings
from django.core.servers.basehttp import FileWrapper
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.fields import BooleanField, CharField
from rest_framework.filters import BaseFilterBackend, OrderingFilter
from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   ListModelMixin, RetrieveModelMixin)
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.relations import PrimaryKeyRelatedField
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer, SerializerMethodField
from rest_framework.viewsets import GenericViewSet

from addons.models import Addon
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import HttpResponseSendFile
from users.models import UserProfile
from versions.models import Version

import mkt.comm.forms as forms
import mkt.constants.comm as comm
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import CORSMixin, MarketplaceView, SilentListModelMixin
from mkt.comm.models import (CommAttachment, CommunicationNote,
                             CommunicationNoteRead, CommunicationThread,
                             user_has_perm_note, user_has_perm_thread)
from mkt.comm.tasks import consume_email, mark_thread_read
from mkt.comm.utils import (create_attachments, create_comm_note,
                            filter_notes_by_read_status)


class AuthorSerializer(ModelSerializer):
    name = CharField()

    class Meta:
        model = UserProfile
        fields = ('name',)


class AttachmentSerializer(ModelSerializer):
    url = SerializerMethodField('get_absolute_url')
    display_name = CharField(source='display_name')
    is_image = BooleanField(source='is_image')

    def get_absolute_url(self, obj):
        return absolutify(obj.get_absolute_url())

    class Meta:
        model = CommAttachment
        fields = ('id', 'created', 'url', 'display_name', 'is_image')


class NoteSerializer(ModelSerializer):
    body = CharField()
    author_meta = AuthorSerializer(source='author', read_only=True)
    reply_to = PrimaryKeyRelatedField(required=False)
    is_read = SerializerMethodField('is_read_by_user')
    attachments = AttachmentSerializer(source='attachments', read_only=True)

    def is_read_by_user(self, obj):
        return obj.read_by_users.filter(
            pk=self.context['request'].amo_user.id).exists()

    class Meta:
        model = CommunicationNote
        fields = ('id', 'created', 'attachments', 'author', 'author_meta',
                  'body', 'is_read', 'note_type', 'reply_to', 'thread')


class AddonSerializer(ModelSerializer):
    name = CharField()
    thumbnail_url = SerializerMethodField('get_icon')
    url = CharField(source='get_absolute_url')
    review_url = SerializerMethodField('get_review_url')

    class Meta:
        model = Addon
        fields = ('name', 'url', 'thumbnail_url', 'app_slug', 'slug',
                  'review_url')

    def get_icon(self, app):
        return app.get_icon_url(64)

    def get_review_url(self, obj):
        return reverse('reviewers.apps.review', args=[obj.app_slug])


class ThreadSerializer(ModelSerializer):
    addon_meta = AddonSerializer(source='addon', read_only=True)
    recent_notes = SerializerMethodField('get_recent_notes')
    notes_count = SerializerMethodField('get_notes_count')
    version_number = SerializerMethodField('get_version_number')
    version_is_obsolete = SerializerMethodField('get_version_is_obsolete')

    class Meta:
        model = CommunicationThread
        fields = ('id', 'addon', 'addon_meta', 'version', 'notes_count',
                  'recent_notes', 'created', 'modified', 'version_number',
                  'version_is_obsolete')
        view_name = 'comm-thread-detail'

    def get_recent_notes(self, obj):
        notes = (obj.notes.with_perms(self.get_request().amo_user, obj)
                          .order_by('-created')[:5])
        return NoteSerializer(
            notes, many=True, context={'request': self.get_request()}).data

    def get_notes_count(self, obj):
        return obj.notes.count()

    def get_version_number(self, obj):
        try:
            return Version.with_deleted.get(id=obj.version_id).version
        except Version.DoesNotExist:
            return ''

    def get_version_is_obsolete(self, obj):
        try:
            return Version.with_deleted.get(id=obj.version_id).deleted
        except Version.DoesNotExist:
            return True


class ThreadPermission(BasePermission):
    """
    Permission wrapper for checking if the authenticated user has the
    permission to view the thread.
    """

    def has_permission(self, request, view):
        # Let `has_object_permission` handle the permissions when we retrieve
        # an object.
        if view.action == 'retrieve':
            return True
        if not request.user.is_authenticated():
            raise PermissionDenied()

        return True

    def has_object_permission(self, request, view, obj):
        """
        Make sure we give correct permissions to read/write the thread.
        """
        if not request.user.is_authenticated() or obj.read_permission_public:
            return obj.read_permission_public

        return user_has_perm_thread(obj, request.amo_user)


class NotePermission(ThreadPermission):

    def has_permission(self, request, view):
        thread_id = view.kwargs.get('thread_id')
        if not thread_id and view.kwargs.get('note_id'):
            note = CommunicationNote.objects.get(id=view.kwargs['note_id'])
            thread_id = note.thread_id

        # We save the thread in the view object so we can use it later.
        view.comm_thread = get_object_or_404(CommunicationThread,
            id=thread_id)

        return ThreadPermission.has_object_permission(self,
            request, view, view.comm_thread)

    def has_object_permission(self, request, view, obj):
        # Has thread obj-level permission AND note obj-level permission.
        return user_has_perm_note(obj, request.amo_user)


class AttachmentPermission(NotePermission):

    def has_permission(self, request, view):
        note = CommunicationNote.objects.get(id=view.kwargs['note_id'])
        return NotePermission.has_object_permission(self, request, view, note)

    def has_object_permission(self, request, view, obj):
        # Has thread obj-level permission AND note obj-level permission.
        note = CommunicationNote.objects.get(id=view.kwargs['note_id'])
        return NotePermission.has_object_permission(self, request, view, note)


class EmailCreationPermission(object):
    """Permit if client's IP address is whitelisted."""

    def has_permission(self, request, view):
        auth_token = request.META.get('HTTP_POSTFIX_AUTH_TOKEN')
        if auth_token and auth_token not in settings.POSTFIX_AUTH_TOKEN:
            return False

        remote_ip = request.META.get('REMOTE_ADDR')
        return remote_ip and (
            remote_ip in settings.WHITELISTED_CLIENTS_EMAIL_API)


class NoAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return request._request.user, None


class ReadUnreadFilter(BaseFilterBackend):
    filter_param = 'show_read'

    def filter_queryset(self, request, queryset, view):
        """
        Return only read notes if `show_read=true` is truthy and only unread
        notes if `show_read=false.
        """
        val = request.GET.get('show_read')
        if val is None:
            return queryset

        show_read = BooleanField().from_native(val)
        return filter_notes_by_read_status(queryset, request.amo_user,
                                           show_read)


class CommViewSet(CORSMixin, MarketplaceView, GenericViewSet):
    """Some overriding and mixin stuff to adapt other viewsets."""
    parser_classes = (FormParser, JSONParser)

    def patched_get_request(self):
        return lambda x: self.request

    def get_serializer_class(self):
        original = super(CommViewSet, self).get_serializer_class()
        original.get_request = self.patched_get_request()

        return original

    def partial_update(self, request, *args, **kwargs):
        val = BooleanField().from_native(request.DATA.get('is_read'))

        if val:
            self.mark_as_read(request.amo_user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response('Requested update operation not supported',
                status=status.HTTP_403_FORBIDDEN)


class ThreadViewSet(SilentListModelMixin, RetrieveModelMixin,
                    DestroyModelMixin, CreateModelMixin, CommViewSet):
    model = CommunicationThread
    serializer_class = ThreadSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (ThreadPermission,)
    filter_backends = (OrderingFilter,)
    cors_allowed_methods = ['get', 'post', 'patch']

    def list(self, request):
        self.serializer_class = ThreadSerializer
        profile = request.amo_user
        # We list all the threads the user has posted a note to.
        notes = list(profile.comm_notes.values_list('thread', flat=True))
        # We list all the threads where the user has been CC'd.
        cc = list(profile.comm_thread_cc.values_list('thread', flat=True))

        # This gives 404 when an app with given slug/id is not found.
        data = {}
        if 'app' in request.GET:
            form = forms.AppSlugForm(request.GET)
            if not form.is_valid():
                raise Http404()

            # TODO: use CommunicationThread.with_perms once other PR merged in.
            queryset = CommunicationThread.objects.filter(pk__in=notes + cc,
                addon=form.cleaned_data['app'])

            # Thread IDs and version numbers from same app.
            data['app_threads'] = list(queryset.order_by('version__version')
                .values('id', 'version__version'))
        else:
            # We list all the threads which uses an add-on authored by the
            # user and with read permissions for add-on devs.
            addons = list(profile.addons.values_list('pk', flat=True))
            q_dev = Q(addon__in=addons, read_permission_developer=True)
            queryset = CommunicationThread.objects.filter(
                Q(pk__in=notes + cc) | q_dev)

        self.queryset = queryset
        res = SilentListModelMixin.list(self, request)
        if res.data:
            res.data.update(data)

        return res

    def retrieve(self, *args, **kwargs):
        res = super(ThreadViewSet, self).retrieve(*args, **kwargs)

        # Thread IDs and version numbers from same app.
        res.data['app_threads'] = list(
            CommunicationThread.objects.filter(addon_id=res.data['addon'])
            .order_by('version__version').values('id', 'version__version'))
        return res

    def create(self, request, *args, **kwargs):
        form = forms.CreateCommThreadForm(request.DATA)
        if not form.is_valid():
            return Response(
                form.errors, status=status.HTTP_400_BAD_REQUEST)

        app = form.cleaned_data['app']
        version = form.cleaned_data['version']
        thread, note = create_comm_note(
            app, version, request.amo_user, form.cleaned_data['body'],
            note_type=form.cleaned_data['note_type'])

        return Response(
            NoteSerializer(note, context={'request': self.request}).data,
            status=status.HTTP_201_CREATED)

    def mark_as_read(self, profile):
        mark_thread_read(self.get_object(), profile)


class NoteViewSet(ListModelMixin, CreateModelMixin, RetrieveModelMixin,
                  DestroyModelMixin, CommViewSet):
    model = CommunicationNote
    serializer_class = NoteSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (NotePermission,)
    filter_backends = (OrderingFilter, ReadUnreadFilter)
    cors_allowed_methods = ['get', 'patch', 'post']

    def get_queryset(self):
        return CommunicationNote.objects.with_perms(
            self.request.amo_user, self.comm_thread)

    def create(self, request, *args, **kwargs):
        thread = get_object_or_404(CommunicationThread, id=kwargs['thread_id'])

        # Validate note.
        form = forms.CreateCommNoteForm(request.DATA)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

        # Create notes.
        thread, note = create_comm_note(
            thread.addon, thread.version, self.request.amo_user,
            form.cleaned_data['body'],
            note_type=form.cleaned_data['note_type'])
        self.attach_as_reply(note)

        return Response(
            NoteSerializer(note, context={'request': request}).data,
            status=status.HTTP_201_CREATED)

    def attach_as_reply(self, note):
        # Overridden in ReplyViewSet.
        pass

    def mark_as_read(self, profile):
        CommunicationNoteRead.objects.get_or_create(note=self.get_object(),
            user=profile)


class AttachmentViewSet(CreateModelMixin, CommViewSet):
    model = CommAttachment
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (AttachmentPermission,)
    cors_allowed_methods = ['get', 'post']

    def get(self, request, note_id, pk, *args, **kwargs):
        attach = get_object_or_404(CommAttachment, pk=pk)
        self.check_object_permissions(request, attach)

        full_path = os.path.join(settings.REVIEWER_ATTACHMENTS_PATH,
                                 attach.filepath)

        content_type = 'application/force-download'
        if attach.is_image():
            content_type = 'image'
        return HttpResponseSendFile(
            request, full_path, content_type=content_type)

    def create(self, request, note_id, *args, **kwargs):
        note = get_object_or_404(CommunicationNote, id=note_id)
        if not note.author.id == request.amo_user.id:
            return Response(
                [{'non_field_errors':
                  'You must be owner of the note to attach a file.'}],
                status=status.HTTP_403_FORBIDDEN)

        # Validate attachment.
        attachment_formset = None
        if request.FILES:
            data = request.POST.copy()
            data.update({
                'form-TOTAL_FORMS': len([k for k in request.FILES if
                                         k.endswith('-attachment')]),
                'form-INITIAL_FORMS': 0,
                'form-MAX_NUM_FORMS': comm.MAX_ATTACH
            })

            if data['form-TOTAL_FORMS'] > comm.MAX_ATTACH:
                # TODO: use formset validate_max=True in Django 1.6.
                return Response(
                    [{'non_field_errors':
                      'Maximum of %s files can be attached.'}],
                    status=status.HTTP_400_BAD_REQUEST)

            attachment_formset = forms.CommAttachmentFormSet(
                data=data, files=request.FILES or None)
            if not attachment_formset.is_valid():
                return Response(attachment_formset.errors,
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response([{'non_field_errors': 'No files were attached.'}],
                            status=status.HTTP_400_BAD_REQUEST)

        # Create attachment.
        if attachment_formset:
            create_attachments(note, attachment_formset)

        return Response(
            NoteSerializer(note, context={'request': request}).data,
            status=status.HTTP_201_CREATED)

    def attach_as_reply(self, note):
        # Overridden in ReplyViewSet.
        pass

    def mark_as_read(self, profile):
        CommunicationNoteRead.objects.get_or_create(note=self.get_object(),
            user=profile)


class ReplyViewSet(NoteViewSet):
    """A note, but a reply to another note."""
    cors_allowed_methods = ['get', 'post']

    def initialize_request(self, request, *args, **kwargs):
        self.parent_note = get_object_or_404(CommunicationNote,
                                             id=kwargs['note_id'])
        return super(ReplyViewSet, self).initialize_request(request, *args,
                                                            **kwargs)

    def get_queryset(self):
        return self.parent_note.replies.all()

    def attach_as_reply(self, obj):
        obj.update(reply_to=self.parent_note)


@api_view(['POST'])
@authentication_classes((NoAuthentication,))
@permission_classes((EmailCreationPermission,))
def post_email(request):
    email_body = request.POST.get('body')
    if not email_body:
        raise ParseError(
            detail='email_body not present in the POST data.')

    consume_email.apply_async((email_body,))
    return Response(status=status.HTTP_201_CREATED)
