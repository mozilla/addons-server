from functools import partial

from rest_framework import fields, serializers

from access import acl
from users.models import UserProfile

from mkt.api.base import CompatRelatedField
from mkt.api.serializers import PotatoCaptchaSerializer


class FeedbackSerializer(PotatoCaptchaSerializer):
    feedback = fields.CharField()
    platform = fields.CharField(required=False)
    chromeless = fields.CharField(required=False)
    from_url = fields.CharField(required=False)
    user = fields.Field()

    def validate(self, attrs):
        attrs = super(FeedbackSerializer, self).validate(attrs)

        if not attrs.get('platform'):
            attrs['platform'] = self.request.GET.get('dev', '')
        attrs['user'] = self.request.amo_user

        return attrs


class LoginSerializer(serializers.Serializer):
    assertion = fields.CharField(required=True)
    audience = fields.CharField(required=False)
    is_mobile = fields.BooleanField(required=False, default=False)


class NewsletterSerializer(serializers.Serializer):
    email = fields.EmailField()


class PermissionsSerializer(serializers.Serializer):
    permissions = fields.SerializerMethodField('get_permissions')

    def get_permissions(self, obj):
        request = self.context['request']
        allowed = partial(acl.action_allowed, request)
        permissions = {
            'admin': allowed('Admin', '%'),
            'developer': request.amo_user.is_app_developer,
            'localizer': allowed('Localizers', '%'),
            'lookup': allowed('AccountLookup', '%'),
            'curator': allowed('Collections', 'Curate'),
            'reviewer': acl.action_allowed(request, 'Apps', 'Review'),
            'webpay': (allowed('Transaction', 'NotifyFailure')
                       and allowed('ProductIcon', 'Create')),
        }
        return permissions


class UserSerializer(serializers.ModelSerializer):
    """
    A wacky serializer type that unserializes PK numbers and
    serializes user fields.
    """
    resource_uri = CompatRelatedField(
        view_name='api_dispatch_detail', read_only=True,
        tastypie={'resource_name': 'settings',
                  'api_name': 'account'},
        source='*')

    class Meta:
        model = UserProfile
        fields = ('display_name', 'resource_uri')

    def field_from_native(self, data, files, field_name, into):
        try:
            value = data[field_name]
        except KeyError:
            if self.required:
                raise serializers.ValidationError(
                    self.error_messages['required'])
            return
        if value in (None, ''):
            obj = None
        else:
            try:
                obj = UserProfile.objects.get(pk=value)
            except UserProfile.DoesNotExist:
                msg = "Invalid pk '%s' - object does not exist." % (data,)
                raise serializers.ValidationError(msg)
        into[self.source or field_name] = obj
