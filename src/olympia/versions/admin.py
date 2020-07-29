from django.contrib import admin

from .models import License, Version


class LicenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


class VersionAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/l10n.css',)
        }
        js = ('js/admin/l10n.js',)

    view_on_site = False
    readonly_fields = ('id', 'created', 'version', 'channel')

    raw_id_fields = ('addon', 'license')

    fieldsets = (
        (None, {
            'fields': (
                'id', 'created', 'addon', 'version', 'channel',
                'release_notes', 'approval_notes', 'license', 'source')
        }),
        ('Flags', {
            'fields': ('deleted',)
        }),
    )


admin.site.register(License, LicenseAdmin)
admin.site.register(Version, VersionAdmin)
