from rest_framework import viewsets

from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowReadOnly, AnyOf, GroupPermission

from .models import FeedItem
from .serializers import FeedItemSerializer


class FeedItemViewSet(viewsets.ModelViewSet):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AnyOf(AllowReadOnly,
                                GroupPermission('Feed', 'Curate'))]
    queryset = FeedItem.objects.all()
    serializer_class = FeedItemSerializer
