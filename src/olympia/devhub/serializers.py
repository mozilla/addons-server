from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext, gettext_lazy as _

from rest_framework import serializers

from olympia.devhub.utils import get_dev_agreement_change_date
from olympia.users.models import UserProfile
from olympia.users.utils import validate_user_name


SUPPORT_CATEGORY_CHOICES = [
    ('policy', _('Technical support for making your add-on compliant')),
    ('technical', _('Issue with addons.mozilla.org')),
    ('other', _('Other')),
]


class SupportSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=255)
    body = serializers.CharField(max_length=10000)
    category = serializers.ChoiceField(choices=SUPPORT_CATEGORY_CHOICES)


class DeveloperAgreementSerializer(serializers.ModelSerializer):
    last_developer_agreement_change = serializers.DateTimeField()

    class Meta:
        model = UserProfile
        fields = ['display_name', 'last_developer_agreement_change']

    def validate_display_name(self, value):
        request_user = self.context['request'].user
        if not request_user.has_anonymous_display_name:
            # See: AgreementForm
            raise serializers.ValidationError('User already has display_name.')
        try:
            return validate_user_name(
                value, error_message=gettext('This display name cannot be used.')
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def validate(self, attrs):
        request_user = self.context['request'].user
        if request_user.has_anonymous_display_name and 'display_name' not in attrs:
            raise serializers.ValidationError(
                {'display_name': ['display_name is required.']}
            )
        return attrs

    def validate_last_developer_agreement_change(self, value):
        if value != get_dev_agreement_change_date():
            raise serializers.ValidationError(
                'Invalid last_developer_agreement_change.'
            )
        return value
