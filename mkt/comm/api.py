from django.conf import settings
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
from rest_framework.relations import PrimaryKeyRelatedField, RelatedField
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer, SerializerMethodField
from rest_framework.viewsets import GenericViewSet

from addons.models import Addon
from amo.urlresolvers import reverse
from users.models import UserProfile
from comm.models import (CommunicationNote, CommunicationNoteRead,
                         CommunicationThread, user_has_perm_note,
                         user_has_perm_thread)
from comm.tasks import consume_email, mark_thread_read
from comm.utils import filter_notes_by_read_status
from versions.models import Version

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import CORSMixin, MarketplaceView, SilentListModelMixin
from mkt.comm.forms import AppSlugForm
from mkt.reviewers.utils import send_note_emails


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
    review_url = SerializerMethodField('get_review_url')

    class Meta:
        model = Addon
        fields = ('name', 'url', 'thumbnail_url', 'app_slug', 'slug',
                  'review_url')

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
        NoteSerializer.get_request = self.get_request
        notes = (obj.notes.with_perms(self.get_request().amo_user, obj)
                          .order_by('-created')[:5])
        return NoteSerializer(notes).data

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
        # Has thread obj-level permission AND note obj-level permission.
        return (
            ThreadPermission.has_object_permission(self, request, view,
                                                   obj.thread) and
            user_has_perm_note(obj, request.amo_user))


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
        notes = profile.comm_notes.values_list('thread', flat=True)
        # We list all the threads where the user has been CC'd.
        cc = profile.comm_thread_cc.values_list('thread', flat=True)

        # This gives 404 when an app with given slug/id is not found.
        data = {}
        if 'app' in request.GET:
            form = AppSlugForm(request.GET)
            if not form.is_valid():
                raise Http404()

            notes, cc = list(notes), list(cc)
            # TODO: use CommunicationThread.with_perms once other PR merged in.
            queryset = CommunicationThread.objects.filter(pk__in=notes + cc,
                addon=form.cleaned_data['app'])

            # Thread IDs and version numbers from same app.
            data['app_threads'] = (queryset.order_by('version__version')
                .values('id', 'version__version'))
        else:
            # We list all the threads which uses an add-on authored by the
            # user and with read permissions for add-on devs.
            notes, cc = list(notes), list(cc)
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
        res.data['app_threads'] = (
            CommunicationThread.objects.filter(addon_id=res.data['addon'])
            .order_by('version__version').values('id', 'version__version'))
        return res

    def mark_as_read(self, profile):
        mark_thread_read(self.get_object(), profile)


class NoteViewSet(ListModelMixin, CreateModelMixin, RetrieveModelMixin,
                  DestroyModelMixin, CommViewSet):
    model = CommunicationNote
    serializer_class = NoteSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication,)
    permission_classes = (NotePermission,)
    filter_backends = (OrderingFilter, ReadUnreadFilter)
    cors_allowed_methods = ['get', 'post', 'delete', 'patch']

    def get_queryset(self):
        return CommunicationNote.objects.with_perms(
            self.request.amo_user, self.comm_thread)

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

    def inherit_permissions(self, obj, parent):
        for key in ('developer', 'reviewer', 'senior_reviewer',
                    'mozilla_contact', 'staff'):
            perm = 'read_permission_%s' % key

            setattr(obj, perm, getattr(parent, perm))

    def post_save(self, obj, created=False):
        if created:
            send_note_emails(obj)

    def pre_save(self, obj):
        """Inherit permissions from the thread."""
        self.inherit_permissions(obj, self.comm_thread)

    def mark_as_read(self, profile):
        CommunicationNoteRead.objects.get_or_create(note=self.get_object(),
            user=profile)


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
        self.inherit_permissions(obj, self.parent_note)
        obj.reply_to = self.parent_note


@api_view(['POST'])
@authentication_classes((NoAuthentication,))
@permission_classes((EmailCreationPermission,))
def post_email(request):
    email_body = request.POST.get('body')
    if not email_body:
        raise ParseError(
            detail='email_body not present in the POST data.')

    consume_email.apply_async((email_body,))
    return Response(status=201)
