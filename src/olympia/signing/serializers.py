import json
import os

from django.urls import reverse

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify, urlparams
from olympia.files.models import FileUpload


class FileUploadSerializer(serializers.ModelSerializer):
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
        super(FileUploadSerializer, self).__init__(*args, **kwargs)

    def get_url(self, instance):
        return absolutify(drf_reverse(
            'signing.version', request=self._context.get('request'),
            args=[instance.addon.guid, instance.version, instance.uuid.hex]))

    def get_validation_url(self, instance):
        return absolutify(
            reverse('devhub.upload_detail', args=[instance.uuid.hex]))

    def _get_download_url(self, file_):
        url = drf_reverse(
            'signing.file', request=self._context.get('request'),
            kwargs={'file_id': file_.id})
        url = os.path.join(url, file_.filename)
        return absolutify(urlparams(url, src='api'))

    def get_files(self, instance):
        if self.version is not None:
            return [{'download_url': self._get_download_url(f),
                     'hash': f.hash,
                     'signed': f.is_signed}
                    for f in self.version.files.all()]
        else:
            return []

    def get_validation_results(self, instance):
        if instance.validation:
            return json.loads(instance.validation)
        else:
            return None

    def get_reviewed(self, instance):
        if self.version is not None:
            return all(file_.reviewed for file_ in self.version.all_files)
        else:
            return False

    def get_active(self, instance):
        if self.version is not None:
            return all(file_.status in amo.REVIEWED_STATUSES
                       for file_ in self.version.all_files)
        else:
            return False

    def get_passed_review(self, instance):
        return self.get_reviewed(instance) and self.get_active(instance)
