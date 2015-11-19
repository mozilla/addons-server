from django.conf import settings
from django.contrib.auth import login

from rest_framework.response import Response
from rest_framework.views import APIView
from waffle.decorators import waffle_switch

from . import verify
from users.models import UserProfile


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
