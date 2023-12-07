from django.shortcuts import get_object_or_404

from rest_framework.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView

from .models import SuppressedEmail
from .serializers import SuppressedEmailSerializer


class SuppressedEmailDetailView(RetrieveAPIView):
    serializer_class = SuppressedEmailSerializer

    def get_object(self):
        email = self.request.query_params.get('email', None)
        if email is not None:
            print('email: ', email)
            return get_object_or_404(SuppressedEmail, email__iexact=email)

        raise ValidationError('email is required')
