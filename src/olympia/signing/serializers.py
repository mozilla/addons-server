import json

from django.urls import reverse as dj_reverse

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.files.models import FileUpload


class SigningFileUploadSerializer(serializers.ModelSerializer):
    guid = serializers.CharField(source='addon.guid')
    active = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    passed_review = serializers.SerializerMethodField()

    # For backwards-compatibility reasons, we return the uuid as "pk".
    pk = serializers.UUIDField(source='uuid', format='hex')
    processed = serializers.BooleanField()
    reviewed = serializers.SerializerMethodField()
    valid = serializers.BooleanField(source='passed_all_validations')
    validation_results = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()

    class Meta:
        model = FileUpload
        fields = [
            'guid',
            'active',
            'automated_signing',
            'url',
            'files',
            'passed_review',
            'pk',
            'processed',
            'reviewed',
            'valid',
            'validation_results',
            'validation_url',
            'version',
        ]

    def __init__(self, *args, **kwargs):
        self.version = kwargs.pop('version', None)
        super().__init__(*args, **kwargs)

    def get_url(self, instance):
        return absolutify(
            drf_reverse(
                'signing.version',
                request=self._context.get('request'),
                args=[instance.addon.guid, instance.version, instance.uuid.hex],
            )
        )

    def get_validation_url(self, instance):
        return absolutify(dj_reverse('devhub.upload_detail', args=[instance.uuid.hex]))

    def _get_download_url(self, file_):
        url = drf_reverse(
            'signing.file',
            request=self._context.get('request'),
            kwargs={'file_id': file_.id, 'filename': file_.pretty_filename},
        )
        return absolutify(url)

    def get_files(self, instance):
        if self.version is not None and (f := self.version.file):
            return [
                {
                    'download_url': self._get_download_url(f),
                    'hash': f.hash,
                    'signed': f.is_signed,
                }
            ]
        else:
            return []

    def get_validation_results(self, instance):
        if instance.validation:
            return json.loads(instance.validation)
        else:
            return None

    def get_reviewed(self, instance):
        return self.version is not None and self.version.file.reviewed

    def get_active(self, instance):
        return (
            self.version is not None
            and self.version.file.status in amo.REVIEWED_STATUSES
        )

    def get_passed_review(self, instance):
        return self.get_reviewed(instance) and self.get_active(instance)
