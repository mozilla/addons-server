from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import ReverseChoiceField

from .models import FileUpload


class FileUploadSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(format='hex')
    channel = ReverseChoiceField(
        choices=[
            (True, amo.CHANNEL_CHOICES_API[amo.RELEASE_CHANNEL_UNLISTED]),
            (False, amo.CHANNEL_CHOICES_API[amo.RELEASE_CHANNEL_LISTED]),
        ],
        source='automated_signing',
    )
    processed = serializers.BooleanField()
    valid = serializers.BooleanField(source='passed_all_validations')
    validation = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = FileUpload
        fields = [
            'uuid',
            'channel',
            'processed',
            'submitted',
            'url',
            'valid',
            'validation',
            'version',
        ]

    def get_validation(self, instance):
        return instance.load_validation() if instance.validation else None

    def get_url(self, instance):
        return absolutify(
            drf_reverse(
                'addon-upload-detail',
                request=self.context.get('request'),
                args=[instance.uuid.hex],
            )
        )
