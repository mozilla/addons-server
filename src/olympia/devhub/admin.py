from django.contrib import admin

from .models import ActivityLog


class HubNewsAdmin(admin.ModelAdmin):
    list_display = ('created', 'user', 'action', 'arguments')
    raw_id_fields = ('user',)
    list_filter = ('action',)
    readonly_fields = ('created', 'user', 'action', '_arguments', '_details')
    date_hierarchy = 'created'
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ActivityLog, HubNewsAdmin)
