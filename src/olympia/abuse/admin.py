from django.contrib import admin
from .models import AbuseReport


class AbuseReportAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon', 'user', 'reporter')
    readonly_fields = ('ip_address', 'message', 'created', 'addon', 'user',
                       'reporter')
    list_display = ('reporter', 'ip_address', 'type', 'target', 'message',
                    'created')
    actions = ('delete_selected',)


admin.site.register(AbuseReport, AbuseReportAdmin)
