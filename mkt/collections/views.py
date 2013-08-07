from django.db import IntegrityError
from django.utils.datastructures import MultiValueDictKeyError

from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestAnonymousAuthentication)
from mkt.api.base import CORSViewSet
from mkt.webapps.models import Webapp

from .authorization import PublisherAuthorization
from .constants import COLLECTIONS_TYPE_BASIC
from .models import Collection
from .serializers import CollectionSerializer


class CollectionViewSet(CORSViewSet, viewsets.ModelViewSet):
    serializer_class = CollectionSerializer
    queryset = Collection.objects.all()
    cors_allowed_methods = ('get', 'post')
    permission_classes = [PublisherAuthorization]
    authentication_classes = [RestOAuthAuthentication,
                              RestAnonymousAuthentication]

    collection_type = COLLECTIONS_TYPE_BASIC

    exceptions = {
        'not_provided': '`app` was not provided.',
        'doesnt_exist': '`app` does not exist.',
        'not_in': '`app` not in collection.',
        'already_in': '`app` already exists in collection.',
        'cant_update': '`apps` cannot be updated this way.'
    }

    def update(self, request, *args, **kwargs):
        if 'apps' in request.DATA:
            raise exceptions.ParseError(detail=self.exceptions['cant_update'])
        return super(CollectionViewSet, self).update(request, *args, **kwargs)

    def return_updated(self, status):
        """
        Passed an HTTP status from rest_framework.status, returns a response
        of that status with the body containing the updated values of
        self.object.
        """
        collection = self.get_object()
        serializer = self.get_serializer(instance=collection)
        return Response(serializer.data, status=status)

    def pre_save(self, obj):
        """
        Allow subclasses of CollectionViewSet to create collections of different
        `collection_type`s by changing the class' `collection_type` property.
        """
        obj.collection_type = self.collection_type
        super(CollectionViewSet, self).pre_save(obj)

    @action()
    def add_app(self, request, pk=None):
        """
        Add an app to the specified collection.
        """
        collection = self.get_object()
        try:
            new_app = Webapp.objects.get(pk=request.DATA['app'])
        except (KeyError, MultiValueDictKeyError):
            raise exceptions.ParseError(detail=self.exceptions['not_provided'])
        except Webapp.DoesNotExist:
            raise exceptions.ParseError(detail=self.exceptions['doesnt_exist'])
        try:
            collection.add_app(new_app)
        except IntegrityError:
            raise exceptions.ParseError(detail=self.exceptions['already_in'])
        return self.return_updated(status.HTTP_200_OK)

    @action()
    def remove_app(self, request, pk=None):
        """
        Add an app to the specified collection.
        """
        collection = self.get_object()
        try:
            to_remove = Webapp.objects.get(pk=request.DATA['app'])
        except (KeyError, MultiValueDictKeyError):
            raise exceptions.ParseError(detail=self.exceptions['not_provided'])
        except Webapp.DoesNotExist:
            raise exceptions.ParseError(detail=self.exceptions['doesnt_exist'])
        removed = collection.remove_app(to_remove)
        if not removed:
            raise exceptions.ParseError(detail=self.exceptions['not_in'])
        return self.return_updated(status.HTTP_200_OK)
