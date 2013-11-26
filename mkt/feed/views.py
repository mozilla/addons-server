from rest_framework import viewsets

from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowReadOnly, AnyOf, GroupPermission

from .models import FeedApp, FeedItem
from .serializers import FeedAppSerializer, FeedItemSerializer


class FeedItemViewSet(viewsets.ModelViewSet):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AnyOf(AllowReadOnly,
                                GroupPermission('Feed', 'Curate'))]
    queryset = FeedItem.objects.all()
    serializer_class = FeedItemSerializer


class FeedAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AnyOf(AllowReadOnly,
                                GroupPermission('Feed', 'Curate'))]
    queryset = FeedApp.objects.all()
    serializer_class = FeedAppSerializer
