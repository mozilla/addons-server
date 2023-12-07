from rest_framework import serializers

from .models import SuppressedEmail


class SuppressedEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuppressedEmail
        fields = '__all__'
