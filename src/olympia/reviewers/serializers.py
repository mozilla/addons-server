from rest_framework.serializers import ModelSerializer

from olympia.addons.models import AddonReviewerFlags


class AddonReviewerFlagsSerializer(ModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = (
            'auto_approval_disabled',
            'needs_admin_code_review',
            'needs_admin_content_review',
            'needs_admin_theme_review',
            'pending_info_request',
        )
