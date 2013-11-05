from rest_framework import fields, serializers

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
