from django import forms
from django.contrib import admin
from django.db.models import Prefetch

from olympia.addons.models import Addon
from olympia.amo.admin import AMOModelAdmin
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.reviewers.models import NeedsHumanReview

from .models import (
    ApplicationsVersions,
    DeniedInstallOrigin,
    InstallOrigin,
    License,
    Version,
    VersionProvenance,
    VersionReviewerFlags,
)


class NeedsHumanReviewInlineForm(forms.ModelForm):
    # Work around for https://code.djangoproject.com/ticket/29947
    # Django admin checks whether each form has changed when saving, and
    # ignores forms with no changes. But for NeedsHumanReviewInline, there
    # might be no changes compared to the default, if the user is adding an
    # active NeedsHumanReview instance. So, always pretend there are changes
    # if the instance is new.
    def has_changed(self):
        if not self.instance or not self.instance.pk:
            return True
        return super().has_changed()


class VersionReviewerFlagsInline(admin.StackedInline):
    model = VersionReviewerFlags
    fields = ('pending_rejection',)
    verbose_name_plural = 'Version Reviewer Flags'
    can_delete = False
    view_on_site = False


class ApplicationsVersionsInline(admin.TabularInline):
    model = ApplicationsVersions
    fields = ('application', 'min', 'max', 'originated_from')
    view_on_site = False
    extra = 0


class NeedsHumanReviewInline(admin.TabularInline):
    model = NeedsHumanReview
    form = NeedsHumanReviewInlineForm
    fields = ('created', 'modified', 'reason', 'is_active')
    readonly_fields = ('reason', 'created', 'modified')
    can_delete = False
    view_on_site = False
    extra = 0


class VersionProvenanceInline(admin.StackedInline):
    model = VersionProvenance
    fields = ('source', 'client_info')
    readonly_fields = ('source', 'client_info')
    can_delete = False
    view_on_site = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


class LicenseAdmin(AMOModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


class VersionAdmin(AMOModelAdmin):
    class Media:
        css = {'all': (vite_asset('css/admin-versions.less'),)}
        js = (vite_asset('js/admin-versions.js'),)

    view_on_site = False
    readonly_fields = ('id', 'created', 'addon', 'version', 'channel')
    list_display = (
        'id',
        'created',
        'addon_guid',
        'version',
        'channel',
        'deleted',
    )

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
        ('Flags', {'fields': ('deleted', 'due_date')}),
    )
    inlines = (
        VersionReviewerFlagsInline,
        NeedsHumanReviewInline,
        ApplicationsVersionsInline,
        VersionProvenanceInline,
    )

    def addon_guid(self, obj):
        return obj.addon.guid

    addon_guid.short_description = 'Add-on GUID'

    def get_queryset(self, request):
        base_qs = Version.unfiltered.all()
        return base_qs.prefetch_related(
            Prefetch('addon', queryset=Addon.unfiltered.all().only_translations()),
        )


class InstallOriginAdmin(AMOModelAdmin):
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


class DeniedInstallOriginAdmin(AMOModelAdmin):
    view_on_site = False
    list_display = ('id', 'hostname_pattern', 'include_subdomains')
    search_fields = ('hostname_pattern',)


admin.site.register(InstallOrigin, InstallOriginAdmin)
admin.site.register(DeniedInstallOrigin, DeniedInstallOriginAdmin)
admin.site.register(License, LicenseAdmin)
admin.site.register(Version, VersionAdmin)
