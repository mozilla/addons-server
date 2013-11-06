from functools import partial

from rest_framework import fields, serializers

from access import acl

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
