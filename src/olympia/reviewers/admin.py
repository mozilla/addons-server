from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin
from olympia.translations.templatetags.jinja_helpers import truncate

from .models import CannedResponse, ReviewActionReason


class CannedResponseAdmin(AMOModelAdmin):
    def truncate_response(obj):
        return truncate(obj.response, 50)

    truncate_response.short_description = 'Response'

    list_display = ('name', truncate_response)
    list_filter = ('type',)


class ReviewActionReasonAdmin(AMOModelAdmin):
    list_display = ('name', 'addon_type', 'is_active')
    list_filter = (
        'addon_type',
        'is_active',
    )
    view_on_site = False


admin.site.register(CannedResponse, CannedResponseAdmin)
admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)
