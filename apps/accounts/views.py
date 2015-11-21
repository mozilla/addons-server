from django.conf import settings
from django.contrib.auth import login

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle.decorators import waffle_switch

from . import verify
from api.jwt_auth.views import JWTProtectedView
from users.models import UserProfile
from accounts.serializers import UserProfileSerializer


class LoginView(APIView):

    @waffle_switch('fxa-auth')
    def post(self, request):
        if 'code' not in request.DATA:
            return Response({'error': 'No code provided.'}, status=400)

        try:
            identity = verify.fxa_identify(request.DATA['code'],
                                           config=settings.FXA_CONFIG)
        except verify.IdentificationError:
            return Response({'error': 'Profile not found.'}, status=401)
        try:
            user = UserProfile.objects.get(email=identity['email'])
        except UserProfile.DoesNotExist:
            return Response({'error': 'User does not exist.'}, status=400)
        else:
            login(request._request, user)
            return Response({'email': identity['email']})


class ProfileView(JWTProtectedView, generics.RetrieveAPIView):
    serializer_class = UserProfileSerializer

    def retrieve(self, request, *args, **kw):
        instance = request.user
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
