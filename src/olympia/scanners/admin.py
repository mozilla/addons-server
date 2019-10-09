import json

from django.contrib import admin
from django.db.models import Prefetch
from django.utils.html import format_html

from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse

from .models import ScannersResult


@admin.register(ScannersResult)
class ScannersResultAdmin(admin.ModelAdmin):
    actions = None
    view_on_site = False

    list_display = ('id', 'formatted_addon', 'channel', 'scanner')
    list_filter = ('scanner',)
    list_select_related = ('version',)

    fields = ('id', 'upload', 'formatted_addon', 'channel', 'scanner',
              'formatted_results')

    def get_queryset(self, request):
        # We already set list_select_related() so we don't need to repeat that.
        # We also need to fetch the add-ons though, and because we need their
        # translations for the name (see formatted_addon() below) we can't use
        # select_related(). We don't want to run the default transformer though
        # so we prefetch them with just the translations.
        return self.model.objects.prefetch_related(
            Prefetch(
                'version__addon',
                queryset=Addon.objects.all().only_translations()
            )
        )

    # Remove the "add" button
    def has_add_permission(self, request):
        return False

    # Remove the "delete" button
    def has_delete_permission(self, request, obj=None):
        return False

    # Read-only mode
    def has_change_permission(self, request, obj=None):
        return False

    def formatted_addon(self, obj):
        if obj.version:
            return format_html(
                '<a href="{}">{} (version: {})</a>',
                reverse('reviewers.review', args=[obj.version.addon.slug]),
                obj.version.addon.name,
                obj.version.id
            )
        return '-'
    formatted_addon.short_description = 'Add-on'

    def channel(self, obj):
        if obj.version:
            return obj.version.get_channel_display()
        return '-'
    channel.short_description = 'Channel'

    def formatted_results(self, obj):
        return format_html('<pre>{}</pre>', json.dumps(obj.results, indent=2))
    formatted_results.short_description = 'Results'
