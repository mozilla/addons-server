from django.contrib import admin
from django.utils.html import format_html
from django.conf.urls import url
from django.shortcuts import get_object_or_404

from olympia.versions.views import download_file
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse

from .models import File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    raw_id_fields = ('version',)
    list_display = (
        '__unicode__', 'addon_slug', 'addon_guid')
    search_fields = (
        '^version__addon__guid',
        '^version__addon__slug',)

    list_select_related = (
        'version__addon',)

    readonly_fields = ('file_download_url',)

    fieldsets = (
        (None, {
            'fields': (
                'version', 'platform', 'filename',
                'size', 'hash', 'original_hash',
                'status', 'file_download_url')
        }),
        ('Details', {
            'fields': (
                'jetpack_version', 'cert_serial_num', 'original_status'),
        }),
        ('Flags', {
            'fields': (
                'is_restart_required', 'strict_compatibility',
                'requires_chrome', 'binary', 'binary_components',
                'is_signed', 'is_multi_package', 'is_experiment',
                'is_webextension', 'is_mozilla_signed_extension')
        }),
    )

    def addon_slug(self, instance):
        return instance.addon.slug

    def addon_guid(self, instance):
        return instance.addon.guid

    def file_download_url(self, instance):
        return format_html(
            '<a href="{}">Download file</a>',
            reverse('admin:files_file_download', args=[instance.pk]))

    file_download_url.short_description = u'Download this file'
    file_download_url.allow_tags = True

    def get_urls(self):
        urls = super(FileAdmin, self).get_urls()
        custom_urls = [
            url(
                r'^([^\/]+?)/download/$',
                self.admin_site.admin_view(self.download_view),
                name='files_file_download'),
        ]

        return custom_urls + urls

    def download_view(self, request, file_id):
        file_ = get_object_or_404(File.objects, pk=file_id)
        addon = get_object_or_404(Addon.unfiltered,
                                  pk=file_.version.addon_id)
        return download_file(request, file_id, file_=file_, addon=addon)
