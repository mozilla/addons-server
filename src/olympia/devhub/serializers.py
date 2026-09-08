from django.utils.translation import gettext_lazy as _

from rest_framework import serializers


SUPPORT_CATEGORY_CHOICES = [
    ('policy', _('Technical support for making your add-on compliant')),
    ('technical', _('Issue with addons.mozilla.org')),
    ('other', _('Other')),
]


class SupportSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=255)
    body = serializers.CharField(max_length=10000)
    category = serializers.ChoiceField(choices=SUPPORT_CATEGORY_CHOICES)
