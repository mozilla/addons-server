from django.contrib import admin

from translations.helpers import truncate

from .models import CannedResponse, EventLog


class CannedResponseAdmin(admin.ModelAdmin):
    def truncate_response(obj):
        return truncate(obj.response, 50)
    truncate_response.short_description = 'Response'

    list_display = ('name', truncate_response)
    list_filter = ('type',)


admin.site.register(CannedResponse, CannedResponseAdmin)


class EventLogAdmin(admin.ModelAdmin):
    list_display = ('created', 'type', 'action', 'field', 'user',
                    'changed_id', 'added', 'removed', 'notes')
    list_filter = ('type', 'action')
    readonly_fields = list_display
    date_hierarchy = 'created'
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(EventLog, EventLogAdmin)
