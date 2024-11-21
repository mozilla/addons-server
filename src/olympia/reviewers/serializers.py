from olympia.addons.models import AddonReviewerFlags
from olympia.api.serializers import AMOModelSerializer


class AddonReviewerFlagsSerializer(AMOModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = (
            'auto_approval_delayed_until',
            'auto_approval_delayed_until_unlisted',
            'auto_approval_disabled',
            'auto_approval_disabled_unlisted',
            'auto_approval_disabled_until_next_approval',
            'auto_approval_disabled_until_next_approval_unlisted',
        )

    def update(self, instance, validated_data):
        # Only update fields that changed. Note that this only supports basic
        # fields.
        if self.partial and instance:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save(update_fields=validated_data.keys())
        else:
            instance = super().update(instance, validated_data)
        return instance
