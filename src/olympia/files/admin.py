from django.contrib import admin
from django.utils.html import format_html

from .models import File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    view_on_site = False

    raw_id_fields = ('version',)
    list_display = ('__str__', 'addon_slug', 'addon_guid')
    search_fields = (
        '^version__addon__guid',
        '^version__addon__slug',
    )

    list_select_related = ('version__addon',)

    readonly_fields = (
        'id',
        'created',
        'file_download_url',
    )

    fieldsets = (
        (
            None,
            {
                'fields': (
                    'id',
                    'created',
                    'version',
                    'size',
                    'hash',
                    'original_hash',
                    'status',
                    'file_download_url',
                    'manifest_version',
                )
            },
        ),
        (
            'Details',
            {
                'fields': ('cert_serial_num', 'original_status'),
            },
        ),
        (
            'Flags',
            {
                'fields': (
                    'strict_compatibility',
                    'is_signed',
                    'is_experiment',
                    'is_mozilla_signed_extension',
                )
            },
        ),
    )

    def addon_slug(self, instance):
        return instance.addon.slug

    def addon_guid(self, instance):
        return instance.addon.guid

    def file_download_url(self, instance):
        return format_html(
            '<a href="{}">{}</a>',
            instance.get_absolute_url(attachment=True),
            instance.pretty_filename or 'Download',
        )

    file_download_url.short_description = 'Download this file'
    file_download_url.allow_tags = True
