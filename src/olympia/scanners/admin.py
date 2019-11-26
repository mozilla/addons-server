from django.conf import settings
from django.conf.urls import url
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db.models import Prefetch
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.translation import ugettext

from urllib.parse import urljoin

from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.constants.scanners import (
    FALSE_POSITIVE,
    RESULT_STATES,
    TRUE_POSITIVE,
    UNKNOWN,
)

from .models import ScannerResult, ScannerRule


class MatchesFilter(SimpleListFilter):
    title = ugettext('matches')
    parameter_name = 'has_matches'

    def lookups(self, request, model_admin):
        return (('all', 'All'), (None, ' With matched rules only'))

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': cl.get_query_string(
                    {self.parameter_name: lookup}, []
                ),
                'display': title,
            }

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        return queryset.filter(has_matches=True)


class StateFilter(SimpleListFilter):
    title = ugettext('state')
    parameter_name = 'state'

    def lookups(self, request, model_admin):
        return (('all', 'All'), *RESULT_STATES.items())

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            selected = (
                lookup == UNKNOWN
                if self.value() is None
                else self.value() == str(lookup)
            )
            yield {
                'selected': selected,
                'query_string': cl.get_query_string(
                    {self.parameter_name: lookup}, []
                ),
                'display': title,
            }

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        if self.value() is None:
            return queryset.filter(state=UNKNOWN)
        return queryset.filter(state=self.value())


class ScannerRuleListFilter(admin.RelatedOnlyFieldListFilter):
    include_empty_choice = False

    def field_choices(self, field, request, model_admin):
        return [
            (rule.pk, f'{rule.name} ({rule.get_scanner_display()})')
            for rule in ScannerRule.objects.only(
                'pk', 'scanner', 'name').order_by('scanner', 'name')
        ]


@admin.register(ScannerResult)
class ScannerResultAdmin(admin.ModelAdmin):
    actions = None
    view_on_site = False

    list_display = (
        'id',
        'formatted_addon',
        'guid',
        'channel',
        'scanner',
        'formatted_matched_rules',
        'created',
        'state',
        'result_actions',
    )
    list_filter = (
        'scanner',
        MatchesFilter,
        StateFilter,
        ('matched_rules', ScannerRuleListFilter),
    )
    list_select_related = ('version',)

    fields = (
        'id',
        'upload',
        'formatted_addon',
        'guid',
        'channel',
        'scanner',
        'created',
        'state',
        'formatted_matched_rules',
        'formatted_results',
    )

    ordering = ('-created',)

    class Media:
        css = {
            'all': ('css/admin/scannerresult.css',)
        }

    def get_queryset(self, request):
        # We already set list_select_related() so we don't need to repeat that.
        # We also need to fetch the add-ons though, and because we need their
        # translations for the name (see formatted_addon() below) we can't use
        # select_related(). We don't want to run the default transformer though
        # so we prefetch them with just the translations.
        return self.model.objects.prefetch_related(
            Prefetch(
                'version__addon',
                # We use `unfiltered` because we want to fetch all the add-ons,
                # including the deleted ones.
                queryset=Addon.unfiltered.all().only_translations(),
            ),
            'matched_rules',
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
                # We use the add-on's ID to support deleted add-ons.
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('reviewers.review', args=[obj.version.addon.id]),
                ),
                obj.version.addon.name,
                obj.version.id,
            )
        return '-'

    formatted_addon.short_description = 'Add-on'

    def guid(self, obj):
        if obj.version:
            return obj.version.addon.guid
        return '-'

    guid.short_description = 'Add-on GUID'
    guid.admin_order_field = 'version__addon__guid'

    def channel(self, obj):
        if obj.version:
            return obj.version.get_channel_display()
        return '-'

    channel.short_description = 'Channel'

    def formatted_results(self, obj):
        return format_html('<pre>{}</pre>', obj.get_pretty_results())

    formatted_results.short_description = 'Results'

    def formatted_matched_rules(self, obj):
        return format_html(
            ', '.join(
                [
                    '<a href="{}">{}</a>'.format(
                        reverse(
                            'admin:scanners_scannerrule_change', args=[rule.pk]
                        ),
                        rule.name,
                    )
                    for rule in obj.matched_rules.all()
                ]
            )
        )

    formatted_matched_rules.short_description = 'Matched rules'

    def handle_true_positive(self, request, pk, *args, **kwargs):
        result = self.get_object(request, pk)
        result.update(state=TRUE_POSITIVE)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} has been marked as true positive.'.format(pk),
        )

        return redirect('admin:scanners_scannerresult_changelist')

    def handle_false_positive(self, request, pk, *args, **kwargs):
        result = self.get_object(request, pk)
        result.update(state=FALSE_POSITIVE)

        title = 'False positive report for ScannerResult {}'.format(pk)
        body = render_to_string(
            'admin/false_positive_report.md', {'result': result}
        )
        labels = ','.join(
            [
                # Default label added to all issues
                'false positive report'
            ] + [
                'rule: {}'.format(rule.name)
                for rule in result.matched_rules.all()
            ]
        )

        return redirect(
            'https://github.com/{}/issues/new?{}'.format(
                result.get_git_repository(),
                urlencode({'title': title, 'body': body, 'labels': labels}),
            )
        )

    def handle_revert(self, request, pk, *args, **kwargs):
        result = self.get_object(request, pk)
        result.update(state=UNKNOWN)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} report has been reverted.'.format(pk),
        )

        return redirect('admin:scanners_scannerresult_changelist')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            url(
                r'^(?P<pk>.+)/report-false-positive/$',
                self.admin_site.admin_view(self.handle_false_positive),
                name='scanners_scannerresult_handlefalsepositive',
            ),
            url(
                r'^(?P<pk>.+)/report-true-positive/$',
                self.admin_site.admin_view(self.handle_true_positive),
                name='scanners_scannerresult_handletruepositive',
            ),
            url(
                r'^(?P<pk>.+)/revert-report/$',
                self.admin_site.admin_view(self.handle_revert),
                name='scanners_scannerresult_handlerevert',
            ),
        ]
        return custom_urls + urls

    def result_actions(self, obj):
        if obj.can_report_feedback():
            return format_html(
                '<a class="button" href="{}">Report as false positive</a>'
                '&nbsp;'
                '<a class="button default" href="{}">'
                'Mark as true positive</a>',
                reverse(
                    'admin:scanners_scannerresult_handlefalsepositive',
                    args=[obj.pk],
                ),
                reverse(
                    'admin:scanners_scannerresult_handletruepositive',
                    args=[obj.pk],
                ),
            )
        elif obj.can_revert_feedback():
            return format_html(
                '<a class="button default" href="{}">Revert report</a>',
                reverse(
                    'admin:scanners_scannerresult_handlerevert',
                    args=[obj.pk],
                ),
            )

    result_actions.short_description = 'Actions'
    result_actions.allow_tags = True


@admin.register(ScannerRule)
class ScannerRuleAdmin(admin.ModelAdmin):
    view_on_site = False

    list_display = ('name', 'scanner', 'action', 'is_active')
    list_filter = ('scanner', 'action', 'is_active')
