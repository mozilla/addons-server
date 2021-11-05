from django.contrib import admin

from .models import InstallOrigin, License, Version, VersionReviewerFlags


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
    list_display = ('id', 'addon_guid', 'version', 'deleted', 'channel')
    list_select_related = ('addon',)

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

    def addon_guid(self, obj):
        return obj.addon.guid

    addon_guid.short_description = 'Add-on GUID'


class InstallOriginAdmin(admin.ModelAdmin):
    view_on_site = False
    raw_id_fields = ('version',)
    readonly_fields = ('id', 'version', 'origin', 'base_domain')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(InstallOrigin, InstallOriginAdmin)
admin.site.register(License, LicenseAdmin)
admin.site.register(Version, VersionAdmin)
