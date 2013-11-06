from django.conf import settings

import basket
from rest_framework import status
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from amo.utils import send_mail_jinja
from users.models import UserProfile

from mkt.account.serializers import (FeedbackSerializer, NewsletterSerializer,
                                     PermissionsSerializer)
from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowSelf
from mkt.api.base import CORSMixin


class MineMixin(object):
    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        if pk == 'mine':
            self.kwargs['pk'] = self.request.amo_user.pk
        return super(MineMixin, self).get_object(queryset)


class CreateAPIViewWithoutModel(CreateAPIView):
    """
    A base class for APIs that need to support a create-like action, but
    without being tied to a Django Model.
    """
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    cors_allowed_methods = ['post']
    permission_classes = (AllowAny,)

    def return_response(self, request, serializer):
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.DATA)
        if serializer.is_valid():
            self.create_action(request, serializer)
            return self.return_response(request, serializer)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FeedbackView(CORSMixin, CreateAPIViewWithoutModel):
    class FeedbackThrottle(UserRateThrottle):
        THROTTLE_RATES = {
            'user': '30/hour',
        }

    serializer_class = FeedbackSerializer
    throttle_classes = (FeedbackThrottle,)
    throttle_scope = 'user'

    def create_action(self, request, serializer):
        context_data = self.get_context_data(request, serializer)
        self.send_email(request, context_data)

    def send_email(self, request, context_data):
        sender = getattr(request.amo_user, 'email', settings.NOBODY_EMAIL)
        send_mail_jinja(u'Marketplace Feedback', 'account/email/feedback.txt',
                        context_data, from_email=sender,
                        recipient_list=[settings.MKT_FEEDBACK_EMAIL])

    def get_context_data(self, request, serializer):
        context_data = {
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'ip_address': request.META.get('REMOTE_ADDR', '')
        }
        context_data.update(serializer.data)
        context_data['user'] = request.amo_user
        return context_data


class NewsletterView(CORSMixin, CreateAPIViewWithoutModel):
    permission_classes = (IsAuthenticated,)
    serializer_class = NewsletterSerializer

    def return_response(self, request, serializer):
        return Response({}, status=status.HTTP_204_NO_CONTENT)

    def create_action(self, request, serializer):
        email = serializer.data['email']
        basket.subscribe(email, 'marketplace',
                         format='H', country=request.REGION.slug,
                         lang=request.LANG, optin='Y',
                         trigger_welcome='Y')


class PermissionsView(CORSMixin, MineMixin, RetrieveAPIView):

    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    cors_allowed_methods = ['get']
    permission_classes = (AllowSelf,)
    model = UserProfile
    serializer_class = PermissionsSerializer
