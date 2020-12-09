from django.contrib import admin

from .models import ActivityLog


class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        'created',
        'user',
        '__str__',
    )
    raw_id_fields = ('user',)
    readonly_fields = (
        'created',
        'user',
        '__str__',
    )
    date_hierarchy = 'created'
    fields = (
        'user',
        'created',
        '__str__',
    )
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ActivityLog, ActivityLogAdmin)
