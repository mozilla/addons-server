from django.contrib import admin

from olympia.scanners.admin import ScannerResultAdmin, MatchesFilter

from .models import YaraResult


@admin.register(YaraResult)
class YaraResultAdmin(ScannerResultAdmin):

    list_display = ('id', 'formatted_addon', 'channel', 'matched_rules')
    list_filter = (MatchesFilter,)
    fields = ('id', 'upload', 'formatted_addon', 'channel',
              'formatted_matches')
