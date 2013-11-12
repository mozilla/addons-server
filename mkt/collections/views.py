from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage as storage
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404
from django.utils.datastructures import MultiValueDictKeyError

from PIL import Image

from rest_framework import generics, status, viewsets
from rest_framework.decorators import action, link
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

from amo.utils import HttpResponseSendFile

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestAnonymousAuthentication,
                                    RestSharedSecretAuthentication)

from mkt.api.base import CORSMixin, SlugOrIdMixin
from mkt.collections.serializers import DataURLImageField
from mkt.webapps.models import Webapp
from users.models import UserProfile

from .authorization import (CanBeHeroAuthorization, CuratorAuthorization,
                            StrictCuratorAuthorization)
from .filters import CollectionFilterSetWithFallback
from .models import Collection
from .serializers import (CollectionMembershipField, CollectionSerializer,
                          CuratorSerializer)


class CollectionViewSet(CORSMixin, SlugOrIdMixin, viewsets.ModelViewSet):
    serializer_class = CollectionSerializer
    queryset = Collection.objects.all()
    cors_allowed_methods = ('get', 'post', 'delete', 'patch')
    permission_classes = [CanBeHeroAuthorization, CuratorAuthorization]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    filter_class = CollectionFilterSetWithFallback

    exceptions = {
        'not_provided': '`app` was not provided.',
        'user_not_provided': '`user` was not provided.',
        'wrong_user_format': '`user` must be an ID or email.',
        'doesnt_exist': '`app` does not exist.',
        'user_doesnt_exist': '`user` does not exist.',
        'not_in': '`app` not in collection.',
        'already_in': '`app` already exists in collection.',
        'app_mismatch': 'All apps in this collection must be included.',
    }

    def filter_queryset(self, queryset):
        queryset = super(CollectionViewSet, self).filter_queryset(queryset)
        self.filter_fallback = getattr(queryset, 'filter_fallback', None)
        self.filter_errors = getattr(queryset, 'filter_errors', None)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super(CollectionViewSet, self).list(
            request, *args, **kwargs)
        if response:
            filter_fallback = getattr(self, 'filter_fallback', None)
            if filter_fallback:
                response['API-Fallback'] = ','.join(filter_fallback)

            filter_errors = getattr(self, 'filter_errors', None)
            if filter_errors:
                # If we had errors filtering, the default behaviour of DRF
                # and django-filter is to produce an empty queryset and ignore
                # the problem. We want to fail loud and clear and expose the
                # errors instead.
                response.data = {
                    'detail': 'Filtering error.',
                    'filter_errors': filter_errors
                }
                response.status_code = status.HTTP_400_BAD_REQUEST
        return response

    def get_object(self, queryset=None):
        """
        Custom get_object implementation to prevent DRF from filtering when we
        do a specific pk/slug/etc lookup (we only want filtering on list API).

        Calls DRF's get_object() with the queryset (filtered or not), since DRF
        get_object() implementation will then just use the queryset without
        attempting to filter it.
        """
        if queryset is None:
            queryset = self.get_queryset()
        if (self.pk_url_kwarg not in self.kwargs and
            self.slug_url_kwarg not in self.kwargs and
            self.lookup_field not in self.kwargs):
            # Only filter queryset if we don't have an explicit lookup.
            queryset = self.filter_queryset(queryset)
        return super(CollectionViewSet, self).get_object(queryset=queryset)

    def get_queryset(self):
        auth = CuratorAuthorization()
        qs = super(CollectionViewSet, self).get_queryset()
        if self.request.user.is_authenticated():
            if auth.has_curate_permission(self.request):
                return qs
            profile = self.request.user.get_profile()
            return qs.filter(Q(curators__id=profile.id) |
                             Q(is_public=True)).distinct()
        return qs.filter(is_public=True)

    def return_updated(self, status, collection=None):
        """
        Passed an HTTP status from rest_framework.status, returns a response
        of that status with the body containing the updated values of
        self.object.
        """
        if collection is None:
            collection = self.get_object()
        serializer = self.get_serializer(instance=collection)
        return Response(serializer.data, status=status)

    @action()
    def duplicate(self, request, pk=None):
        """
        Duplicate the specified collection, copying over all fields and apps.
        Anything passed in request.DATA will override the corresponding value
        on the resulting object.
        """
        # Serialize data from specified object, removing the id and then
        # updating with custom data in request.DATA.
        collection = self.get_object()
        collection_data = self.get_serializer(instance=collection).data
        collection_data.pop('id')
        collection_data.update(request.DATA)

        # Pretend we didn't have anything in kwargs (removing 'pk').
        self.kwargs = {}

        # Override request.DATA with the result from above.
        request._data = collection_data

        # Now create the collection.
        result = self.create(request)
        if result.status_code != status.HTTP_201_CREATED:
            return result

        # And now, add apps from the original collection.
        for app in collection.apps():
            self.object.add_app(app)

        # Re-Serialize to include apps.
        return self.return_updated(status.HTTP_201_CREATED,
                                   collection=self.object)

    @action()
    def add_app(self, request, pk=None):
        """
        Add an app to the specified collection.
        """
        collection = self.get_object()
        try:
            new_app = Webapp.objects.get(pk=request.DATA['app'])
        except (KeyError, MultiValueDictKeyError):
            raise ParseError(detail=self.exceptions['not_provided'])
        except Webapp.DoesNotExist:
            raise ParseError(detail=self.exceptions['doesnt_exist'])
        try:
            collection.add_app(new_app)
        except IntegrityError:
            raise ParseError(detail=self.exceptions['already_in'])
        return self.return_updated(status.HTTP_200_OK)

    @action()
    def remove_app(self, request, pk=None):
        """
        Remove an app from the specified collection.
        """
        collection = self.get_object()
        try:
            to_remove = Webapp.objects.get(pk=request.DATA['app'])
        except (KeyError, MultiValueDictKeyError):
            raise ParseError(detail=self.exceptions['not_provided'])
        except Webapp.DoesNotExist:
            raise ParseError(detail=self.exceptions['doesnt_exist'])
        removed = collection.remove_app(to_remove)
        if not removed:
            return Response(status=status.HTTP_205_RESET_CONTENT)
        return self.return_updated(status.HTTP_200_OK)

    @action()
    def reorder(self, request, pk=None):
        """
        Reorder the specified collection.
        """
        collection = self.get_object()
        def membership(app):
            f = CollectionMembershipField()
            f.context = {'request': request}
            return f.to_native(app)
        try:
            collection.reorder(request.DATA)
        except ValueError:
            return Response({
                'detail': self.exceptions['app_mismatch'],
                'apps': [membership(a) for a in
                         collection.collectionmembership_set.all()]
            }, status=status.HTTP_400_BAD_REQUEST, exception=True)
        return self.return_updated(status.HTTP_200_OK)

    def serialized_curators(self, no_cache=False):
        queryset = self.get_object().curators.all()
        if no_cache:
            queryset = queryset.no_cache()
        return Response([CuratorSerializer(instance=c).data for c in queryset])

    def get_curator(self, request):
        try:
            userdata = request.DATA['user']
            if (isinstance(userdata, int) or isinstance(userdata, basestring)
                and userdata.isdigit()):
                return UserProfile.objects.get(pk=userdata)
            else:
                validate_email(userdata)
                return UserProfile.objects.get(email=userdata)
        except (KeyError, MultiValueDictKeyError):
            raise ParseError(detail=self.exceptions['user_not_provided'])
        except UserProfile.DoesNotExist:
            raise ParseError(detail=self.exceptions['user_doesnt_exist'])
        except ValidationError:
            raise ParseError(detail=self.exceptions['wrong_user_format'])

    @link(permission_classes=[StrictCuratorAuthorization])
    def curators(self, request, pk=None):
        return self.serialized_curators()

    @action(methods=['POST'])
    def add_curator(self, request, pk=None):
        self.get_object().add_curator(self.get_curator(request))
        return self.serialized_curators(no_cache=True)

    @action(methods=['POST'])
    def remove_curator(self, request, pk=None):
        removed = self.get_object().remove_curator(self.get_curator(request))
        if not removed:
            return Response(status=status.HTTP_205_RESET_CONTENT)
        return self.serialized_curators(no_cache=True)


class CollectionImageViewSet(CORSMixin, viewsets.ViewSet,
                             generics.RetrieveUpdateAPIView,
                             generics.DestroyAPIView):
    queryset = Collection.objects.all()
    permission_classes = [CuratorAuthorization]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    cors_allowed_methods = ('get', 'put', 'delete')

    def retrieve(self, request, pk=None):
        obj = self.get_object()
        if not obj.has_image:
            raise Http404
        return HttpResponseSendFile(request, obj.image_path(),
                                    content_type='image/png')

    def update(self, request, *a, **kw):
        obj = self.get_object()
        try:
            img = DataURLImageField().from_native(request.read())
        except ValidationError:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        i = Image.open(img)
        with storage.open(obj.image_path(), 'wb') as f:
            i.save(f, 'png')
        obj.update(has_image=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.has_image:
            storage.delete(obj.image_path())
            obj.update(has_image=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
