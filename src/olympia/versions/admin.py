from django import forms
from django.contrib import admin

from .models import License, Version


class LicenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


class VersionAdmin(admin.ModelAdmin):
    view_on_site = False
    readonly_fields = ('version', 'channel')

    raw_id_fields = ('addon', 'license')

    fieldsets = (
        (None, {
            'fields': (
                'addon', 'version', 'channel', 'release_notes',
                'approval_notes', 'license', 'source')
        }),
        ('Flags', {
            'fields': ('deleted',)
        }),
    )

    def formfield_for_dbfield(self, db_field, **kwargs):
        formfield = super(VersionAdmin, self).formfield_for_dbfield(
            db_field, **kwargs)
        if db_field.name == 'release_notes':
            formfield.widget = forms.Textarea(attrs=formfield.widget.attrs)
        return formfield


admin.site.register(License, LicenseAdmin)
admin.site.register(Version, VersionAdmin)
