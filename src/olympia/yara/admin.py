import json

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Q
from django.utils.html import format_html
from django.utils.translation import ugettext

from olympia.scanners.admin import ScannersResultAdmin

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
class YaraResultAdmin(ScannersResultAdmin):

    list_display = ('id', 'formatted_addon', 'channel', 'matched_rules')
    list_filter = (MatchesFilter,)
    fields = ('id', 'upload', 'formatted_addon', 'channel',
              'formatted_matches')

    def formatted_matches(self, obj):
        return format_html('<pre>{}</pre>', json.dumps(obj.matches, indent=4))
    formatted_matches.short_description = 'Matches'
