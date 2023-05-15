from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin

from .models import NeedsHumanReview, ReviewActionReason


class ReviewActionReasonAdmin(AMOModelAdmin):
    list_display = ('name', 'addon_type', 'is_active')
    list_filter = (
        'addon_type',
        'is_active',
    )
    view_on_site = False


admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)


class NeedsHumanReviewAdmin(AMOModelAdmin):
    list_display = ('__str__',)
    raw_id_fields = ('version',)
    view_on_site = False
    list_select_related = ('version', 'version__addon')


admin.site.register(NeedsHumanReview, NeedsHumanReviewAdmin)
