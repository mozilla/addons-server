from django.contrib import admin

from .models import DiscoveryModule


class DiscoveryModuleAdmin(admin.ModelAdmin):
    list_display = ('module', 'app', 'ordering', 'locales')


admin.site.register(DiscoveryModule, DiscoveryModuleAdmin)
