from django.contrib import admin
from django.db.models import Prefetch
from django.utils.html import format_html

from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse

from .models import GitExtractionEntry


@admin.register(GitExtractionEntry)
class GitExtractionEntryAdmin(admin.ModelAdmin):
    actions = None
    view_on_site = False

    list_display = (
        'id',
        'formatted_addon',
        'in_progress',
        'created',
        'modified',
    )

    ordering = ('created',)

    # Remove the "add" button
    def has_add_permission(self, request):
        return False

    # Read-only mode
    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        # We need to fetch the add-ons, and because we need their translations
        # for the name (see formatted_addon() below), we can't use
        # select_related(). We don't want to run the default transformer though
        # so we prefetch them with just the translations.
        return self.model.objects.prefetch_related(
            Prefetch(
                'addon',
                # We use `unfiltered` because we want to fetch all the add-ons,
                # including the deleted ones.
                queryset=Addon.unfiltered.all().only_translations(),
            )
        )

    def formatted_addon(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:addons_addon_change', args=(obj.addon.pk,)),
            obj.addon.name,
        )

    formatted_addon.short_description = 'Add-on'
