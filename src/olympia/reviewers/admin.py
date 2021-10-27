from django.contrib import admin

from olympia.translations.templatetags.jinja_helpers import truncate

from .models import CannedResponse, ReviewActionReason, ReviewerScore


class CannedResponseAdmin(admin.ModelAdmin):
    def truncate_response(obj):
        return truncate(obj.response, 50)

    truncate_response.short_description = 'Response'

    list_display = ('name', truncate_response)
    list_filter = ('type',)


class ReviewerScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'score', 'note_key', 'note', 'created')
    raw_id_fields = ('user', 'addon')
    fieldsets = (
        (
            None,
            {
                'fields': ('user', 'addon', 'score', 'note'),
            },
        ),
    )
    list_filter = ('note_key',)


class ReviewActionReasonAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('name',)


admin.site.register(CannedResponse, CannedResponseAdmin)
admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)
admin.site.register(ReviewerScore, ReviewerScoreAdmin)
