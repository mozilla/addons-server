from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin

from .models import NeedsHumanReview, ReviewActionReason, UsageTier


class ReviewActionReasonAdmin(AMOModelAdmin):
    list_display = ('name', 'addon_type', 'is_active')
    list_filter = (
        'addon_type',
        'is_active',
    )
    view_on_site = False


admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)


class UsageTierAdmin(AMOModelAdmin):
    list_display = (
        'name',
        'lower_adu_threshold',
        'upper_adu_threshold',
    )
    view_on_site = False
    fields = (
        'name',
        'lower_adu_threshold',
        'upper_adu_threshold',
        'growth_threshold_before_flagging',
    )


admin.site.register(UsageTier, UsageTierAdmin)


class NeedsHumanReviewAdmin(AMOModelAdmin):
    list_display = ('addon_guid', 'version', 'created', 'is_active')
    list_filter = ('is_active',)
    raw_id_fields = ('version',)
    view_on_site = False
    list_select_related = ('version', 'version__addon')
    fields = ('created', 'modified', 'reason', 'version', 'is_active')
    readonly_fields = ('reason', 'created', 'modified')

    def addon_guid(self, obj):
        return obj.version.addon.guid


admin.site.register(NeedsHumanReview, NeedsHumanReviewAdmin)
