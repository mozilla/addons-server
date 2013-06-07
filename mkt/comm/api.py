from functools import partial

from django.db.models import Q
from django.http import Http404

from rest_framework.exceptions import PermissionDenied
from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   ListModelMixin, RetrieveModelMixin)
from rest_framework.permissions import BasePermission
from rest_framework.relations import HyperlinkedRelatedField, RelatedField
from rest_framework.serializers import ModelSerializer
from rest_framework.viewsets import GenericViewSet

from access import acl
from comm.models import (CommunicationNote, CommunicationThread,
                         CommunicationThreadCC)
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.webpay.forms import PrepareForm


class NoteSerializer(ModelSerializer):
    thread = HyperlinkedRelatedField(read_only=True,
                                     view_name='comm-thread-detail')
    body = RelatedField('body')

    class Meta:
        model = CommunicationNote
        fields = ('id', 'author', 'note_type', 'body', 'created', 'thread')


class ThreadSerializer(ModelSerializer):
    notes = HyperlinkedRelatedField(read_only=True, many=True,
                                    view_name='comm-note-detail')

    class Meta:
        model = CommunicationThread
        fields = ('id', 'addon', 'version', 'notes', 'created')
        view_name = 'comm-thread-detail'


class ThreadPermission(BasePermission):
    """
    Permission wrapper for checking if the authenticated user has the
    permission to view the thread.
    """

    def check_acls(self, request, obj, acl_type):
        if acl_type == 'moz_contact':
            return request.user.email == obj.addon.mozilla_contact
        elif acl_type == 'admin':
            return acl.action_allowed(request, 'Admin', '%')
        elif acl_type == 'reviewer':
            return acl.action_allowed(request, 'Apps', 'Review')
        elif acl_type == 'senior_reviewer':
            return acl.action_allowed(request, 'Apps', 'ReviewEscalated')
        else:
            raise 'Invalid ACL lookup.'

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

        Developers of the add-on used in the thread, users in the CC list,
        and users who post to the thread are allowed to access the object.

        Moreover, other object permissions are also checked agaisnt the ACLs
        of the user.
        """

        if not request.user.is_authenticated() or obj.read_permission_public:
            return obj.read_permission_public

        profile = request.amo_user
        user_post = CommunicationNote.objects.filter(author=profile,
            thread=obj)
        user_cc = CommunicationThreadCC.objects.filter(user=profile,
            thread=obj)
        if user_post.exists() or user_cc.exists():
            return True

        check_acls = partial(self.check_acls, request, obj)

        # User is a developer of the add-on and has the permission to read.
        user_is_author = profile.addons.filter(pk=obj.addon_id)
        if obj.read_permission_developer and user_is_author.exists():
            return True

        if obj.read_permission_reviewer and check_acls('reviewer'):
            return True

        if (obj.read_permission_senior_reviewer and check_acls(
            'senior_reviewer')):
            return True

        if (obj.read_permission_mozilla_contact and check_acls(
            'moz_contact')):
            return True

        if obj.read_permission_staff and check_acls('admin'):
            return True

        return False


class NotePermission(ThreadPermission):
    def has_object_permission(self, request, view, obj):
        return super(ThreadPermission, self).has_object_permission(request,
            view, obj.thread)


class ThreadViewSet(ListModelMixin, RetrieveModelMixin, DestroyModelMixin,
                    CreateModelMixin, GenericViewSet):
    model = CommunicationThread
    serializer_class = ThreadSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = (ThreadPermission,)

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
            # user.
            notes, cc = list(notes), list(cc)
            addons = list(profile.addons.values_list('pk', flat=True))
            queryset = CommunicationThread.objects.filter(
                Q(pk__in=notes + cc) | Q(addon__in=addons))

        self.queryset = queryset
        return ListModelMixin.list(self, request)


class NoteViewSet(CreateModelMixin, RetrieveModelMixin, DestroyModelMixin,
                  GenericViewSet):
    model = CommunicationNote
    serializer_class = NoteSerializer
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication,)
    permission_classes = (NotePermission,)
