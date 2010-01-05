from django.contrib import admin

from .models import HubPromo, HubEvent


class HubPromoAdmin(admin.ModelAdmin):
    list_display = ('heading', 'body', 'visibility')
    list_editable = ('visibility',)


class HubEventAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'location', 'date')


admin.site.register(HubPromo, HubPromoAdmin)
admin.site.register(HubEvent, HubEventAdmin)
