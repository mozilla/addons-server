import json

from rest_framework import serializers

import amo
from files.models import FileUpload
from mkt.api.fields import ReverseChoiceField
from mkt.webapps.models import Webapp


class AppStatusSerializer(serializers.ModelSerializer):
    status = ReverseChoiceField(choices_dict=amo.STATUS_CHOICES_API,
                                required=False)
    disabled_by_user = serializers.BooleanField(required=False)

    allowed_statuses = {
        # You can push to the pending queue.
        amo.STATUS_NULL: amo.STATUS_PENDING,
        # You can push to public if you've been reviewed.
        amo.STATUS_PUBLIC_WAITING: amo.STATUS_PUBLIC,
    }

    class Meta:
        model = Webapp
        fields = ('status', 'disabled_by_user')

    def validate_status(self, attrs, source):
        if not self.object:
            raise serializers.ValidationError(u'Error getting app.')

        if not source in attrs:
            return attrs

        # An incomplete app's status can not be changed.
        valid, reasons = self.object.is_fully_complete()
        if not valid:
            raise serializers.ValidationError(reasons)

        # Only some specific changes are possible depending on the app current
        # status.
        if (self.object.status not in self.allowed_statuses or
            attrs[source] != self.allowed_statuses[self.object.status]):
                raise serializers.ValidationError(
                    'App status can not be changed to the one you specified.')

        return attrs


class FileUploadSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    processed = serializers.BooleanField(read_only=True)

    class Meta:
        model = FileUpload
        fields = ('id', 'processed', 'valid', 'validation')

    def transform_validation(self, obj, value):
        return json.loads(value) if value else value
