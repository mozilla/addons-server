from django.contrib import admin

from .models import HubPromo, HubEvent, ActivityLog


class HubPromoAdmin(admin.ModelAdmin):
    list_display = ('heading', 'body', 'visibility')
    list_editable = ('visibility',)


class HubEventAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'location', 'date')


class HubNewsAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'arguments')
    raw_id_fields = ('user',)
    list_filter = ('action',)


admin.site.register(HubPromo, HubPromoAdmin)
admin.site.register(HubEvent, HubEventAdmin)
admin.site.register(ActivityLog, HubNewsAdmin)
