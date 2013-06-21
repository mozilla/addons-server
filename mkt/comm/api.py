from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ParseError
from rest_framework.fields import BooleanField, CharField
from rest_framework.filters import BaseFilterBackend, OrderingFilter
from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   ListModelMixin, RetrieveModelMixin)
from rest_framework.permissions import BasePermission
from rest_framework.relations import PrimaryKeyRelatedField, RelatedField
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from addons.models import Addon
from users.models import UserProfile
from comm.models import CommunicationNote, CommunicationThread
from comm.tasks import consume_email
from comm.utils import filter_notes_by_read_status, ThreadObjectPermission
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import CORSViewSet
from mkt.webpay.forms import PrepareForm
from rest_framework.response import Response


class PatchSerializerViewSet(CORSViewSet):
    """
    Overrides `get_serializer_class` to patch the serializer class
    with a method to access the request object within the serializer methods.
    """
    def patched_get_request(self):
        return lambda x: self.request

    def get_serializer_class(self):
        original = super(PatchSerializerViewSet, self).get_serializer_class()
        original.get_request = self.patched_get_request()

        return original


class AuthorSerializer(ModelSerializer):
    name = CharField()

    class Meta:
        model = UserProfile
        fields = ('name',)


class NoteSerializer(ModelSerializer):
    body = CharField()
    author_meta = AuthorSerializer(source='author', read_only=True)
    reply_to = PrimaryKeyRelatedField(required=False)
    is_read = SerializerMethodField('is_read_by_user')

    def is_read_by_user(self, obj):
        return obj.read_by_users.filter(
            pk=self.get_request().amo_user.id).exists()

    class Meta:
        model = CommunicationNote
        fields = ('id', 'author', 'author_meta', 'note_type', 'body',
                  'created', 'thread', 'reply_to', 'is_read')


class AddonSerializer(ModelSerializer):
    name = CharField()
    thumbnail_url = RelatedField('thumbnail_url')
    url = CharField(source='get_absolute_url')

    class Meta:
        model = Addon
        fields = ('name', 'url', 'thumbnail_url', 'slug')


class ThreadSerializer(ModelSerializer):
    addon_meta = AddonSerializer(source='addon', read_only=True)
    recent_notes = SerializerMethodField('get_recent_notes')
    notes_count = SerializerMethodField('get_notes_count')

    class Meta:
        model = CommunicationThread
        fields = ('id', 'addon', 'addon_meta', 'version', 'notes_count',
                  'recent_notes', 'created', 'modified')
        view_name = 'comm-thread-detail'

    def get_recent_notes(self, obj):
        NoteSerializer.get_request = self.get_request
        return NoteSerializer(obj.notes.all().order_by('-created')[:5]).data

    def get_notes_count(self, obj):
        return obj.notes.count()


class ThreadPermission(BasePermission, ThreadObjectPermission):
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

        profile = request.amo_user
        return self.user_has_permission(obj, profile)


class NotePermission(ThreadPermission):

    def has_permission(self, request, view):
        thread_id = view.kwargs['thread_id']
        # We save the thread in the view object so we can use it later.
        view.comm_thread = get_object_or_404(CommunicationThread,
            id=thread_id)

        if view.action == 'list':
            return ThreadPermission.has_object_permission(self,
                request, view, view.comm_thread)

        if view.action == 'create':
            if not request.user.is_authenticated():
                return False

            # Determine permission to add the note based on the thread
            # permission.
            return ThreadPermission.has_object_permission(self,
                request, view, view.comm_thread)

        return True

    def has_object_permission(self, request, view, obj):
        return ThreadPermission.has_object_permission(self, request, view,
            obj.thread)


class ThreadViewSet(ListModelMixin, RetrieveModelMixin, DestroyModelMixin,
                    CreateModelMixin, PatchSerializerViewSet):
    model = CommunicationThread
    serializer_class = ThreadSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (ThreadPermission,)
    filter_backends = (OrderingFilter,)
    cors_allowed_methods = ['get', 'post']

    def list(self, request):
        self.serializer_class = ThreadSerializer
        profile = request.amo_user
        # We list all the threads the user has posted a note to.
        notes = profile.comm_notes.values_list('thread', flat=True)
        # We list all the threads where the user has been CC'd.
        cc = profile.comm_thread_cc.values_list('thread', flat=True)

        # This gives 404 when an app with given slug/id is not found.
        if 'app' in request.GET:
            form = PrepareForm(request.GET)
            if not form.is_valid():
                raise Http404()

            notes, cc = list(notes), list(cc)
            queryset = CommunicationThread.objects.filter(pk__in=notes + cc,
                addon=form.cleaned_data['app'])
        else:
            # We list all the threads which uses an add-on authored by the
            # user and with read permissions for add-on devs.
            notes, cc = list(notes), list(cc)
            addons = list(profile.addons.values_list('pk', flat=True))
            q_dev = Q(addon__in=addons, read_permission_developer=True)
            queryset = CommunicationThread.objects.filter(
                Q(pk__in=notes + cc) | q_dev)

        self.queryset = queryset
        return ListModelMixin.list(self, request)


class ReadUnreadFilter(BaseFilterBackend):
    filter_param = 'show_read'

    def filter_queryset(self, request, queryset, view):
        """
        Return only read notes if `show_read=true` is truthy and only unread
        notes if `show_read=false.
        """
        val = request.GET.get(self.filter_param)
        if val is None:
            return queryset

        return filter_notes_by_read_status(queryset, request.amo_user,
                                           BooleanField().from_native(val))


class NoteViewSet(ListModelMixin, CreateModelMixin, RetrieveModelMixin,
                  DestroyModelMixin, PatchSerializerViewSet):
    model = CommunicationNote
    serializer_class = NoteSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication,)
    permission_classes = (NotePermission,)
    filter_backends = (OrderingFilter, ReadUnreadFilter)
    cors_allowed_methods = ['get', 'post', 'delete']

    def get_queryset(self):
        return CommunicationNote.objects.filter(thread=self.comm_thread)

    def get_serializer(self, instance=None, data=None,
                       files=None, many=False, partial=False):
        if self.action == 'create':
            # HACK: We want to set the `author` as the current user
            # (read-only), yet we can't specify `author` as a `read_only`
            # field because then the serializer won't pick it up at the time
            # of deserialization.
            data_dict = {'author': self.request.amo_user.id,
                         'thread': self.comm_thread.id,
                         'note_type': data['note_type'],
                         'body': data['body']}
        else:
            data_dict = data

        return super(NoteViewSet, self).get_serializer(data=data_dict,
            files=files, instance=instance, many=many, partial=partial)

    def pre_save(self, obj):
        """Inherit permissions from the thread."""
        for key in ('developer', 'reviewer', 'senior_reviewer',
                    'mozilla_contact', 'staff'):
            perm = 'read_permission_%s' % key
            setattr(obj, perm, getattr(self.comm_thread, perm))


class EmailCreationPermission(object):
    def has_permission(self, request, view):
        remote_ip = request.META.get('REMOTE_ADDR')
        return remote_ip and (
            remote_ip in settings.WHITELISTED_CLIENTS_EMAIL_API)


@api_view(['POST'])
@permission_classes((EmailCreationPermission,))
def post_email(request):
    email_body = request.POST.get('email_body')
    if not email_body:
        raise ParseError(
            detail='email_body not present in the POST data.')

    consume_email.apply_async((email_body,))
    return Response(status=201)


class ReplyViewSet(NoteViewSet):
    cors_allowed_methods = ['get', 'post']

    def initialize_request(self, request, *args, **kwargs):
        self.parent_note = get_object_or_404(CommunicationNote,
                                             id=kwargs['note_id'])

        return super(ReplyViewSet, self).initialize_request(request, *args,
                                                            **kwargs)

    def get_queryset(self):
        return self.parent_note.replies.all()

    def pre_save(self, obj):
        """Inherit permissions from the parent note."""
        for key in ('developer', 'reviewer', 'senior_reviewer',
                    'mozilla_contact', 'staff'):
            perm = 'read_permission_%s' % key
            setattr(obj, perm, getattr(self.parent_note, perm))

        obj.reply_to = self.parent_note
