import json

from django.contrib import admin
from django.utils.html import format_html

from olympia import amo
from olympia.amo.urlresolvers import reverse

from .models import YaraResult


@admin.register(YaraResult)
class YaraResultAdmin(admin.ModelAdmin):
    actions = None

    list_display = ('id', 'formatted_addon', 'channel', 'matched_rules')
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
