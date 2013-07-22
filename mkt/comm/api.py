from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ParseError
from rest_framework.fields import CharField
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   ListModelMixin, RetrieveModelMixin)
from rest_framework.permissions import BasePermission
from rest_framework.relations import RelatedField
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from addons.models import Addon
from users.models import UserProfile
from comm.models import CommunicationNote, CommunicationThread
from comm.tasks import consume_email
from comm.utils import ThreadObjectPermission
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import CORSViewSet
from mkt.webpay.forms import PrepareForm
from rest_framework.response import Response


class AuthorSerializer(ModelSerializer):
    name = CharField()

    class Meta:
        model = UserProfile
        fields = ('name',)


class NoteSerializer(ModelSerializer):
    body = CharField()
    author_meta = AuthorSerializer(source='author', read_only=True)

    class Meta:
        model = CommunicationNote
        fields = ('id', 'author', 'author_meta', 'note_type', 'body',
                  'created', 'thread')


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
                    CreateModelMixin, CORSViewSet):
    model = CommunicationThread
    serializer_class = ThreadSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (ThreadPermission,)
    filter_backends = (OrderingFilter,)
    cors_allowed_methods = ['get', 'post']

    def list(self, request):
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


class NoteViewSet(ListModelMixin, CreateModelMixin, RetrieveModelMixin,
                  DestroyModelMixin, CORSViewSet):
    model = CommunicationNote
    serializer_class = NoteSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication,)
    permission_classes = (NotePermission,)
    filter_backends = (OrderingFilter,)
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
