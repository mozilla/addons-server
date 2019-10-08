import json

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Q
from django.utils.html import format_html
from django.utils.translation import ugettext

from olympia import amo
from olympia.amo.urlresolvers import reverse

from .models import YaraResult


class MatchesFilter(SimpleListFilter):
    title = ugettext('matches')
    parameter_name = 'matches'

    def lookups(self, request, model_admin):
        return (
            (None, 'With matched rules only'),
            ('all', 'With/without matched rules'),
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
        return queryset.filter(~Q(matches='[]'))


@admin.register(YaraResult)
class YaraResultAdmin(admin.ModelAdmin):
    actions = None
    view_on_site = False

    list_display = ('id', 'formatted_addon', 'channel', 'matched_rules')
    list_filter = (MatchesFilter,)
    list_select_related = ('version',)

    fields = ('id', 'upload', 'formatted_addon', 'channel',
              'formatted_matches')

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
        return "-"
    formatted_addon.short_description = 'Add-on'

    def channel(self, obj):
        if obj.version:
            return ('listed' if obj.version.channel ==
                    amo.RELEASE_CHANNEL_LISTED else 'unlisted')
        return "-"
    channel.short_description = 'Channel'

    def formatted_matches(self, obj):
        return format_html('<pre>{}</pre>', json.dumps(obj.matches, indent=4))
    formatted_matches.short_description = 'Matches'
