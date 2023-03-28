from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin

from .models import ReviewActionReason


class ReviewActionReasonAdmin(AMOModelAdmin):
    list_display = ('name', 'addon_type', 'is_active')
    list_filter = (
        'addon_type',
        'is_active',
    )
    view_on_site = False


admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)
