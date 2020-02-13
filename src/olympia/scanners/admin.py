from django.conf import settings
from django.conf.urls import url
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db.models import FieldDoesNotExist, Prefetch
from django.http import Http404
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.http import urlencode, is_safe_url
from django.utils.translation import ugettext

from urllib.parse import urljoin, urlparse

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.constants.scanners import (
    ABORTING,
    FALSE_POSITIVE,
    INCONCLUSIVE,
    NEW,
    RESULT_STATES,
    RUNNING,
    SCHEDULED,
    TRUE_POSITIVE,
    UNKNOWN,
    YARA,
)

from .models import (
    ImproperScannerQueryRuleStateError, ScannerQueryResult, ScannerQueryRule,
    ScannerResult, ScannerRule
)
from .tasks import run_yara_query_rule


def _is_safe_url(url, request):
    """Override the Django `is_safe_url()` to pass a configured list of allowed
    hosts and enforce HTTPS."""
    allowed_hosts = (
        settings.DOMAIN,
        urlparse(settings.EXTERNAL_SITE_URL).netloc,
    )
    require_https = request.is_secure() if request else False
    return is_safe_url(url, allowed_hosts=allowed_hosts,
                       require_https=require_https)


class PresenceFilter(SimpleListFilter):
    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': cl.get_query_string(
                    {self.parameter_name: lookup}, []
                ),
                'display': title,
            }


class MatchesFilter(PresenceFilter):
    title = ugettext('presence of matched rules')
    parameter_name = 'has_matched_rules'

    def lookups(self, request, model_admin):
        return (('all', 'All'), (None, ' With matched rules only'))

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
            for rule in field.related_model.objects.only(
                'pk', 'scanner', 'name'
            ).order_by('scanner', 'name')
        ]


class WithVersionFilter(PresenceFilter):
    title = ugettext('presence of a version')
    parameter_name = 'has_version'

    def lookups(self, request, model_admin):
        return (('all', 'All'), (None, ' With version only'))

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        return queryset.exclude(version=None)


class AbstractScannerResultAdminMixin(admin.ModelAdmin):
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
        WithVersionFilter,
    )
    list_select_related = ('version',)
    raw_id_fields = ('version', 'upload')

    fields = (
        'id',
        'upload',
        'formatted_addon',
        'guid',
        'channel',
        'scanner',
        'created',
        'state',
        'formatted_matched_rules_with_files',
        'formatted_results',
        'result_actions',
    )

    ordering = ('-created',)

    class Media:
        css = {'all': ('css/admin/scannerresult.css',)}

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

    # Custom actions
    def has_actions_permission(self, request):
        return acl.action_allowed(
            request, amo.permissions.ADMIN_SCANNERS_RESULTS_EDIT)

    def get_list_display(self, request):
        fields = super().get_list_display(request)
        return self._excludes_fields(request=request, fields=fields)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        return self._excludes_fields(request=request, fields=fields)

    def _excludes_fields(self, request, fields):
        to_exclude = []
        if not self.has_actions_permission(request):
            to_exclude = ['result_actions']
        try:
            self.model._meta.get_field('upload')
        except FieldDoesNotExist:
            to_exclude.append('upload')
        fields = list(filter(lambda x: x not in to_exclude, fields))
        return fields

    def formatted_addon(self, obj):
        if obj.version:
            return format_html(
                '<a href="{}">{} (version: {})</a>',
                # We use the add-on's ID to support deleted add-ons.
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse(
                        'reviewers.review',
                        args=[
                            ('listed' if obj.version.channel ==
                             amo.RELEASE_CHANNEL_LISTED else 'unlisted'),
                            obj.version.addon.id,
                        ],
                    ),
                ),
                obj.version.addon.name,
                obj.version.version,
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
        rule_model = self.model.matched_rules.rel.model
        info = rule_model._meta.app_label, rule_model._meta.model_name

        return format_html(
            ', '.join(
                [
                    '<a href="{}">{}</a>'.format(
                        reverse(
                            'admin:%s_%s_change' % info, args=[rule.pk]
                        ),
                        rule.name,
                    )
                    for rule in obj.matched_rules.all()
                ]
            )
        )

    formatted_matched_rules.short_description = 'Matched rules'

    def formatted_matched_rules_with_files(self, obj):
        files_by_matched_rules = obj.get_files_by_matched_rules()
        rule_model = self.model.matched_rules.rel.model
        info = rule_model._meta.app_label, rule_model._meta.model_name
        return render_to_string(
            'admin/scanners/scannerresult/'
            'formatted_matched_rules_with_files.html',
            {
                'rule_change_urlname': 'admin:%s_%s_change' % info,
                'external_site_url': settings.EXTERNAL_SITE_URL,
                'file_id': (obj.version.all_files[0].id if obj.version else
                            None),
                'matched_rules': [
                    {
                        'pk': rule.pk,
                        'name': rule.name,
                        'files': files_by_matched_rules[rule.name],
                    }
                    for rule in obj.matched_rules.all()
                ]
            },
        )

    formatted_matched_rules_with_files.short_description = 'Matched rules'

    def safe_referer_redirect(self, request, default_url):
        referer = request.META.get('HTTP_REFERER')
        if referer and _is_safe_url(referer, request):
            return redirect(referer)
        return redirect(default_url)

    def handle_true_positive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != "POST":
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=TRUE_POSITIVE)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} has been marked as true positive.'.format(pk),
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def handle_inconclusive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != "POST":
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=INCONCLUSIVE)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} has been marked as inconclusive.'.format(pk),
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def handle_false_positive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != "POST":
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=FALSE_POSITIVE)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} has been marked as false positive.'.format(pk),
        )

        title = 'False positive report for ScannerResult {}'.format(pk)
        body = render_to_string(
            'admin/false_positive_report.md', {'result': result, 'YARA': YARA}
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
        is_admin = acl.action_allowed(
            request, amo.permissions.ADMIN_SCANNERS_RESULTS_EDIT)
        if not is_admin or request.method != "POST":
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=UNKNOWN)

        messages.add_message(
            request,
            messages.INFO,
            'Scanner result {} report has been reverted.'.format(pk),
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        custom_urls = [
            url(
                r'^(?P<pk>.+)/report-false-positive/$',
                self.admin_site.admin_view(self.handle_false_positive),
                name='%s_%s_handlefalsepositive' % info,
            ),
            url(
                r'^(?P<pk>.+)/report-true-positive/$',
                self.admin_site.admin_view(self.handle_true_positive),
                name='%s_%s_handletruepositive' % info,
            ),
            url(
                r'^(?P<pk>.+)/report-inconclusive/$',
                self.admin_site.admin_view(self.handle_inconclusive),
                name='%s_%s_handleinconclusive' % info,
            ),
            url(
                r'^(?P<pk>.+)/revert-report/$',
                self.admin_site.admin_view(self.handle_revert),
                name='%s_%s_handlerevert' % info,
            ),
        ]
        return custom_urls + urls

    def result_actions(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        return render_to_string(
            'admin/scannerresult_actions.html', {
                'handlefalsepositive_urlname': (
                    'admin:%s_%s_handlefalsepositive' % info
                ),
                'handletruepositive_urlname': (
                    'admin:%s_%s_handletruepositive' % info
                ),
                'handleinconclusive_urlname': (
                    'admin:%s_%s_handleinconclusive' % info
                ),
                'handlerevert_urlname': 'admin:%s_%s_handlerevert' % info,
                'obj': obj,
            }
        )

    result_actions.short_description = 'Actions'
    result_actions.allow_tags = True


class AbstractScannerRuleAdminMixin(admin.ModelAdmin):
    view_on_site = False

    list_display = ('name', 'scanner', 'action', 'is_active')
    list_filter = ('scanner', 'action', 'is_active')
    fields = (
        'scanner',
        'name',
        'action',
        'created',
        'modified',
        'matched_results_link',
        'is_active',
        'definition',
    )
    readonly_fields = ('created', 'modified', 'matched_results_link')

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if not self.has_change_permission(request, obj):
            # Remove the 'definition' field...
            fields = list(filter(lambda x: x != 'definition', fields))
            # ...and add its readonly (and pretty!) alter-ego.
            fields.append('formatted_definition')
        return fields

    def matched_results_link(self, obj):
        if not obj.pk or not obj.scanner:
            return '-'
        count = obj.results.count()
        ResultModel = obj.results.model
        url = reverse(
            'admin:{}_{}_changelist'.format(
                ResultModel._meta.app_label, ResultModel._meta.model_name
            )
        )
        url = (
            f'{url}?matched_rules__id__exact={obj.pk}'
            f'&{WithVersionFilter.parameter_name}=all'
            f'&{StateFilter.parameter_name}=all'
            f'&scanner={obj.scanner}'
        )
        return format_html('<a href="{}">{}</a>', url, count)

    matched_results_link.short_description = 'Matched Results'

    def formatted_definition(self, obj):
        return format_html('<pre>{}</pre>', obj.definition)
    formatted_definition.short_description = 'Definition'


@admin.register(ScannerResult)
class ScannerResultAdmin(AbstractScannerResultAdminMixin, admin.ModelAdmin):
    pass


@admin.register(ScannerQueryResult)
class ScannerQueryResultAdmin(
        AbstractScannerResultAdminMixin, admin.ModelAdmin):
    raw_id_fields = ('version',)

    def has_actions_permission(self, request):
        return acl.action_allowed(
            request, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT)


@admin.register(ScannerRule)
class ScannerRuleAdmin(AbstractScannerRuleAdminMixin, admin.ModelAdmin):
    pass


@admin.register(ScannerQueryRule)
class ScannerQueryRuleAdmin(AbstractScannerRuleAdminMixin, admin.ModelAdmin):
    list_display = (
        'name', 'scanner', 'state_with_actions', 'matched_results_link',
    )
    list_filter = ('state',)
    fields = (
        'scanner',
        'state_with_actions',
        'name',
        'created',
        'modified',
        'matched_results_link',
        'definition',
    )
    readonly_fields = (
        'created', 'modified', 'matched_results_link', 'state_with_actions',
    )

    def has_change_permission(self, request, obj=None):
        if obj and obj.state != NEW:
            return False
        return super().has_change_permission(request, obj=obj)

    def handle_run(self, request, pk, *args, **kwargs):
        is_admin = acl.action_allowed(
            request, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT)
        if not is_admin or request.method != 'POST':
            raise Http404

        rule = self.get_object(request, pk)
        try:
            # SCHEDULED is a transitional state that allows us to update the UI
            # right away before redirecting. Once it starts being processed the
            # task will switch it to RUNNING.
            rule.change_state_to(SCHEDULED)
            run_yara_query_rule.delay(rule.pk)

            messages.add_message(
                request,
                messages.INFO,
                'Scanner Query Rule {} has been successfully queued for '
                'execution.'.format(rule.pk),
            )
        except ImproperScannerQueryRuleStateError:
            messages.add_message(
                request,
                messages.ERROR,
                'Scanner Query Rule {} could not be queued for execution '
                'because it was in "{}"" state.'.format(
                    rule.pk, rule.get_state_display()),
            )

        return redirect('admin:scanners_scannerqueryrule_changelist')

    def handle_abort(self, request, pk, *args, **kwargs):
        is_admin = acl.action_allowed(
            request, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT)
        if not is_admin or request.method != 'POST':
            raise Http404

        rule = self.get_object(request, pk)
        try:
            rule.change_state_to(ABORTING)  # Tasks will take this into account
            # FIXME: revoke existing tasks (would need to extract the
            # GroupResult when executing the chord, store its id in the rule,
            # then restore the GroupResult here to call revoke() on it)
            messages.add_message(
                request,
                messages.INFO,
                'Scanner Query Rule {} is being aborted.'.format(rule.pk),
            )
        except ImproperScannerQueryRuleStateError:
            # We messed up somewhere.
            messages.add_message(
                request,
                messages.ERROR,
                'Scanner Query Rule {} could not be aborted because it was '
                'in "{}" state'.format(rule.pk, rule.get_state_display()),
            )

        return redirect('admin:scanners_scannerqueryrule_changelist')

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        custom_urls = [
            url(
                r'^(?P<pk>.+)/abort/$',
                self.admin_site.admin_view(self.handle_abort),
                name='%s_%s_handle_abort' % info,
            ),
            url(
                r'^(?P<pk>.+)/run/$',
                self.admin_site.admin_view(self.handle_run),
                name='%s_%s_handle_run' % info,
            ),
        ]
        return custom_urls + urls

    def state_with_actions(self, obj):
        return render_to_string(
            'admin/scannerqueryrule_state_with_actions.html', {
                'obj': obj,
                'NEW': NEW,
                'RUNNING': RUNNING,
            }
        )
    state_with_actions.short_description = 'State'
    state_with_actions.allow_tags = True
