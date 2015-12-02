from django.contrib import admin

from .models import License, Version


class LicenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


admin.site.register(License, LicenseAdmin)
admin.site.register(Version)
