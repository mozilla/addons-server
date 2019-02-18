from rest_framework import serializers

from olympia.abuse.models import AbuseReport
from olympia.accounts.serializers import BaseUserSerializer


class BaseAbuseReportSerializer(serializers.ModelSerializer):
    reporter = BaseUserSerializer(read_only=True)

    class Meta:
        model = AbuseReport
        fields = ('message', 'reporter')

    def validate_target(self, data, target_name):
        if target_name not in data:
            msg = serializers.Field.default_error_messages['required']
            raise serializers.ValidationError({
                target_name: [msg]
            })

    def to_internal_value(self, data):
        output = super(BaseAbuseReportSerializer, self).to_internal_value(data)
        request = self.context['request']
        output['ip_address'] = request.META.get('REMOTE_ADDR')
        if request.user.is_authenticated:
            output['reporter'] = request.user
        return output


class AddonAbuseReportSerializer(BaseAbuseReportSerializer):
    addon = serializers.SerializerMethodField()

    class Meta:
        model = AbuseReport
        fields = BaseAbuseReportSerializer.Meta.fields + (
            'addon',
        )

    def to_internal_value(self, data):
        self.validate_target(data, 'addon')
        view = self.context.get('view')
        output = {
            # get_guid() needs to be called first because get_addon_object()
            # would otherwise 404 on add-ons that don't match an existing
            # add-on in our database.
            'guid': view.get_guid(),
            'addon': view.get_addon_object(),
        }
        # Pop 'addon' before passing it to super(), we already have the
        # output value.
        data.pop('addon')
        output.update(
            super(AddonAbuseReportSerializer, self).to_internal_value(data)
        )
        return output

    def get_addon(self, obj):
        addon = obj.addon
        if not addon and not obj.guid:
            return None
        return {
            'guid': addon.guid if addon else obj.guid,
            'id': addon.id if addon else None,
            'slug': addon.slug if addon else None,
        }


class UserAbuseReportSerializer(BaseAbuseReportSerializer):
    user = BaseUserSerializer(required=False)  # We validate it ourselves.

    class Meta:
        model = AbuseReport
        fields = BaseAbuseReportSerializer.Meta.fields + (
            'user',
        )

    def to_internal_value(self, data):
        view = self.context.get('view')
        self.validate_target(data, 'user')
        output = {
            'user': view.get_user_object()
        }
        # Pop 'user' before passing it to super(), we already have the
        # output value and did the validation above.
        data.pop('user')
        output.update(
            super(UserAbuseReportSerializer, self).to_internal_value(data)
        )
        return output
