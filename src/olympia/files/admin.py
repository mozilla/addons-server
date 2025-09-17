from django.contrib import admin
from django.utils.html import format_html

from olympia.amo.admin import AMOModelAdmin

from .models import File, FileManifest, FileValidation, WebextPermission


class FileValidationInline(admin.StackedInline):
    model = FileValidation
    fields = ('valid', 'errors', 'warnings', 'notices', 'validation')
    readonly_fields = fields
    can_delete = False
    view_on_site = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


class WebextPermissionInline(admin.StackedInline):
    model = WebextPermission
    fields = (
        'permissions',
        'optional_permissions',
        'host_permissions',
        'data_collection_permissions',
        'optional_data_collection_permissions',
    )
    readonly_fields = fields
    can_delete = False
    view_on_site = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


class FileManifestInline(admin.StackedInline):
    model = FileManifest
    fields = ('manifest_data',)
    readonly_fields = fields
    can_delete = False
    view_on_site = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(File)
class FileAdmin(AMOModelAdmin):
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
        'version',
        'size',
        'hash',
        'original_hash',
        'file_download_url',
        'manifest_version',
        'cert_serial_num',
        'original_status',
        'status_disabled_reason',
        'strict_compatibility',
        'is_signed',
        'is_experiment',
        'is_mozilla_signed_extension',
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
                'fields': (
                    'cert_serial_num',
                    'original_status',
                    'status_disabled_reason',
                ),
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

    inlines = (FileValidationInline, FileManifestInline, WebextPermissionInline)

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
