from django.contrib import admin

from .models import (
    DeniedInstallOrigin,
    InstallOrigin,
    License,
    Version,
    VersionReviewerFlags,
)


class VersionReviewerFlagsInline(admin.StackedInline):
    model = VersionReviewerFlags
    fields = ('pending_rejection', 'needs_human_review_by_mad')
    verbose_name_plural = 'Version Reviewer Flags'
    can_delete = False
    view_on_site = False


class LicenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


class VersionAdmin(admin.ModelAdmin):
    class Media:
        css = {'all': ('css/admin/l10n.css',)}
        js = ('js/admin/l10n.js',)

    view_on_site = False
    readonly_fields = ('id', 'created', 'version', 'channel')

    raw_id_fields = ('addon', 'license')

    fieldsets = (
        (
            None,
            {
                'fields': (
                    'id',
                    'created',
                    'addon',
                    'version',
                    'channel',
                    'release_notes',
                    'approval_notes',
                    'license',
                    'source',
                )
            },
        ),
        ('Flags', {'fields': ('deleted', 'needs_human_review')}),
    )
    inlines = (VersionReviewerFlagsInline,)


class InstallOriginAdmin(admin.ModelAdmin):
    view_on_site = False
    raw_id_fields = ('version',)
    list_display = ('id', 'addon_guid', 'version_version', 'origin', 'base_domain')
    list_select_related = (
        'version',
        'version__addon',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def addon_guid(self, obj):
        return obj.version.addon.guid

    addon_guid.short_description = 'Add-on GUID'

    def version_version(self, obj):
        return obj.version.version

    version_version.short_description = 'Version'


class DeniedInstallOriginAdmin(admin.ModelAdmin):
    view_on_site = False
    list_display = ('id', 'hostname_pattern', 'include_subdomains')
    search_fields = ('hostname_pattern',)


admin.site.register(InstallOrigin, InstallOriginAdmin)
admin.site.register(DeniedInstallOrigin, DeniedInstallOriginAdmin)
admin.site.register(License, LicenseAdmin)
admin.site.register(Version, VersionAdmin)
