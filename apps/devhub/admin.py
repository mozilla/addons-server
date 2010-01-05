from django.contrib import admin

from .models import HubPromo, HubEvent, AddonLog


class HubPromoAdmin(admin.ModelAdmin):
    list_display = ('heading', 'body', 'visibility')
    list_editable = ('visibility',)


class HubEventAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'location', 'date')


class HubNewsAdmin(admin.ModelAdmin):
    list_display = ('addon', 'user', 'type', 'notes')
    raw_id_fields = ('addon', 'user')
    list_filter = ('type',)


admin.site.register(HubPromo, HubPromoAdmin)
admin.site.register(HubEvent, HubEventAdmin)
admin.site.register(AddonLog, HubNewsAdmin)
