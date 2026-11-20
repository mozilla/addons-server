from django import forms

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import ReverseChoiceField
from olympia.api.serializers import AMOModelSerializer

from .models import FileUpload
from .utils import parse_addon


class FileUploadSerializer(AMOModelSerializer):
    uuid = serializers.UUIDField(format='hex')
    channel = ReverseChoiceField(choices=list(amo.CHANNEL_CHOICES_API.items()))
    processed = serializers.BooleanField()
    valid = serializers.BooleanField(source='passed_all_validations')
    validation = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    manifest_data = serializers.SerializerMethodField()

    class Meta:
        model = FileUpload
        fields = [
            'uuid',
            'channel',
            'manifest_data',
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

    def get_manifest_data(self, instance):
        if (
            getattr(self.context.get('view'), 'action', None) == 'list'
            or not instance.passed_all_validations
            or instance.submitted
        ):
            return None
        try:
            parsed = parse_addon(instance, minimal=True)
        except forms.ValidationError:
            return None
        parsed = Addon.resolve_webext_translations(parsed, instance)
        return {field: parsed.get(field) for field in ('name', 'summary', 'homepage')}
