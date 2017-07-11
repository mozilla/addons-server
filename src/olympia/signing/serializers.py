import json

from django.core.urlresolvers import reverse

from rest_framework import serializers

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
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
        return absolutify(reverse('signing.version', args=[instance.addon.guid,
                                                           instance.version,
                                                           instance.uuid.hex]))

    def get_validation_url(self, instance):
        return absolutify(reverse('devhub.upload_detail',
                                  args=[instance.uuid.hex]))

    def get_files(self, instance):
        if self.version is not None:
            return [{'download_url': f.get_signed_url('api'),
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
