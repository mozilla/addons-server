from django.contrib import admin

from .models import CannedResponse, EventLog


class CannedResponseAdmin(admin.ModelAdmin):
    list_display = ('name', 'response')


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
