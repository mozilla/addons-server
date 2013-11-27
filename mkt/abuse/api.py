from rest_framework import generics, serializers, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.throttling import UserRateThrottle

from abuse.models import AbuseReport

from mkt.account.serializers import UserSerializer
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestAnonymousAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import check_potatocaptcha, CORSMixin
from mkt.api.fields import SlugOrPrimaryKeyRelatedField, SplitField
from mkt.webapps.api import AppSerializer
from mkt.webapps.models import Webapp


class AbuseThrottle(UserRateThrottle):
    THROTTLE_RATES = {
        'user': '30/hour',
    }


class BaseAbuseSerializer(serializers.ModelSerializer):
    text = serializers.CharField(source='message')
    ip_address = serializers.CharField(required=False)
    reporter = SplitField(serializers.PrimaryKeyRelatedField(required=False),
                          UserSerializer())

    def save(self, force_insert=False):
        serializers.ModelSerializer.save(self)
        del self.data['ip_address']
        return self.object


class UserAbuseSerializer(BaseAbuseSerializer):
    user = SplitField(serializers.PrimaryKeyRelatedField(), UserSerializer())

    class Meta:
        model = AbuseReport
        fields = ('text', 'ip_address', 'reporter', 'user')


class AppAbuseSerializer(BaseAbuseSerializer):
    app = SplitField(
        SlugOrPrimaryKeyRelatedField(source='addon', slug_field='app_slug',
                                     queryset=Webapp.objects.all()),
        AppSerializer(source='addon'))

    class Meta:
        model = AbuseReport
        fields = ('text', 'ip_address', 'reporter', 'app')


class BaseAbuseViewSet(CORSMixin, generics.CreateAPIView,
                       viewsets.ModelViewSet):
    cors_allowed_methods = ['post']
    throttle_classes = (AbuseThrottle,)
    throttle_scope = 'user'
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = (AllowAny,)

    def create(self, request, *a, **kw):
        fail = check_potatocaptcha(request.DATA)
        if fail:
            return fail
        # Immutable? *this* *is* PYYYYTHONNNNNNNNNN!
        request.DATA._mutable = True
        if request.amo_user:
            request.DATA['reporter'] = request.amo_user.pk
        else:
            request.DATA['reporter'] = None
        request.DATA['ip_address'] = request.META.get('REMOTE_ADDR', '')
        return viewsets.ModelViewSet.create(self, request, *a, **kw)

    def post_save(self, obj, created=False):
        obj.send()


class AppAbuseViewSet(BaseAbuseViewSet):
    serializer_class = AppAbuseSerializer


class UserAbuseViewSet(BaseAbuseViewSet):
    serializer_class = UserAbuseSerializer
