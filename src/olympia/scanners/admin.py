import json

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Prefetch
from django.utils.html import format_html
from django.utils.translation import ugettext

from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse

from .models import ScannerResult, ScannerRule


class MatchesFilter(SimpleListFilter):
    title = ugettext('matches')
    parameter_name = 'has_matches'

    def lookups(self, request, model_admin):
        return (
            ('all', 'All'),
            (None, ' With matched rules only'),
        )

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': cl.get_query_string({
                    self.parameter_name: lookup,
                }, []),
                'display': title,
            }

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        return queryset.filter(has_matches=True)


@admin.register(ScannerResult)
class ScannerResultAdmin(admin.ModelAdmin):
    actions = None
    view_on_site = False

    list_display = ('id', 'formatted_addon', 'channel', 'scanner',
                    'matched_rules')
    list_filter = ('scanner', MatchesFilter)
    list_select_related = ('version',)

    fields = ('id', 'upload', 'formatted_addon', 'channel', 'scanner',
              'formatted_results')

    ordering = ('-created',)

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


@admin.register(ScannerRule)
class ScannerRuleAdmin(admin.ModelAdmin):
    view_on_site = False

    list_display = ('name', 'action', 'is_active')
    list_filter = ('action', 'is_active')
