from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db.models import Count, Prefetch
from django.http import Http404
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import re_path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode
from django.utils.text import capfirst

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo.admin import (
    AMOModelAdmin,
    DateRangeFilter,
    MultipleRelatedListFilter,
    NumericRangeFilter,
)
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.amo.utils import is_safe_url
from olympia.api.models import APIKey
from olympia.constants import scanners
from olympia.constants.scanners import (
    ABORTING,
    COMPLETED,
    CUSTOMS,
    FALSE_POSITIVE,
    INCONCLUSIVE,
    NARC,
    NEW,
    RESULT_STATES,
    RUNNING,
    SCHEDULED,
    TRUE_POSITIVE,
    UNKNOWN,
    WEBHOOK,
    WEBHOOK_EVENTS,
    YARA,
)
from olympia.users.models import UserProfile

from .models import (
    ImproperScannerQueryRuleStateError,
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
    ScannerWebhook,
    ScannerWebhookEvent,
)
from .tasks import run_scanner_query_rule


@admin.display(description='Matched Rules')
def formatted_matched_rules_with_files_and_data(
    obj,
    *,
    display_data=False,
    display_scanner=False,
    limit_to=100,
    template_name='formatted_matched_rules_with_files',
):
    files_and_data_by_matched_rules = obj.get_files_and_data_by_matched_rules()
    info = obj.rule_model._meta.app_label, obj.rule_model._meta.model_name
    rules = (
        [obj.matched_rule] if hasattr(obj, 'matched_rule') else obj.matched_rules.all()
    )

    return render_to_string(
        f'admin/scanners/scannerresult/{template_name}.html',
        {
            'obj': obj,
            'limit_to': limit_to,
            'display_data': display_data,
            'display_scanner': display_scanner,
            'rule_change_urlname': 'admin:%s_%s_change' % info,
            'external_site_url': settings.EXTERNAL_SITE_URL,
            'file_id': (obj.version.file.id if obj.version else None),
            'matched_rules': [
                {
                    'pk': rule.pk,
                    'name': str(rule),
                    'description': str(rule.description),
                    'scanner': rule.get_scanner_display(),
                    'files_and_data': files_and_data_by_matched_rules[rule.name][
                        :limit_to
                    ],
                    'files_not_shown': len(files_and_data_by_matched_rules[rule.name])
                    - limit_to,
                }
                for rule in rules
            ],
            'addon_id': obj.version.addon.pk if obj.version else None,
            'version_id': obj.version.pk if obj.version else None,
            'addon_guid': obj.version.addon.guid if obj.version else None,
            'addon_version': obj.version if obj.version else None,
        },
    )


class PresenceFilter(SimpleListFilter):
    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
            }


class MatchesFilter(PresenceFilter):
    title = 'presence of matched rules'
    parameter_name = 'has_matched_rules'

    def lookups(self, request, model_admin):
        return (('all', 'All'), (None, ' With matched rules only'))

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        return queryset.filter(has_matches=True)


class StateFilter(SimpleListFilter):
    title = 'result state'
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
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
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
            (rule.pk, f'{rule} ({rule.get_scanner_display()})')
            for rule in field.related_model.objects.only(
                'pk', 'scanner', 'pretty_name', 'name'
            ).order_by('scanner', 'pretty_name', 'name')
        ]


class ExcludeMatchedRulesFilter(MultipleRelatedListFilter):
    title = 'Excluding results solely matching these rules'
    parameter_name = 'exclude_rule'

    def lookups(self, request, model_admin):
        # None is not included, since it's a <select multiple> to remove all
        # rules the user should deselect all <option> from the dropdown.
        return [
            (rule.pk, f'{rule} ({rule.get_scanner_display()})')
            for rule in ScannerRule.objects.only(
                'pk', 'scanner', 'pretty_name', 'name'
            ).order_by('scanner', 'pretty_name', 'name')
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value is None:
            return queryset
        # We can't just exclude the list of rules, because then it would hide
        # results even if they match another rule. So we reverse the logic and
        # filter results on all rules except those passed. Unfortunately
        # because that can cause a result to appear several times we need a
        # distinct().
        return queryset.filter(
            matched_rules__in=ScannerRule.objects.exclude(pk__in=value)
        ).distinct()


class WithVersionFilter(PresenceFilter):
    title = 'presence of a version'
    parameter_name = 'has_version'

    def lookups(self, request, model_admin):
        return (('all', 'All'), (None, ' With version only'))

    def queryset(self, request, queryset):
        if self.value() == 'all':
            return queryset
        return queryset.exclude(version=None)


class VersionChannelFilter(admin.ChoicesFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'version channel'


class VersionCreatedFilter(DateRangeFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'version creation date'


class AddonCreatedFilter(DateRangeFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'add-on creation date'


class AddonLastUpdatedFilter(DateRangeFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'add-on last updated date'


class AddonStatusFilter(admin.ChoicesFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'add-on status'


class AddonVisibilityFilter(admin.BooleanFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'add-on listing visibility'

    def choices(self, changelist):
        # We're doing a lookup on disabled_by_user: if it's True then the
        # add-on listing is "invisible", and False it's "visible".
        for lookup, title in (
            (None, 'All'),
            ('1', 'Invisible'),
            ('0', 'Visible'),
        ):
            yield {
                'selected': self.lookup_val == lookup and not self.lookup_val2,
                'query_string': changelist.get_query_string(
                    {self.lookup_kwarg: lookup}, [self.lookup_kwarg2]
                ),
                'display': title,
            }


class AddonAverageDailyUsers(NumericRangeFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'add-on ADU'


class FileStatusFilter(admin.ChoicesFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'file status'


class FileIsSignedFilter(admin.BooleanFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'file signature'


class AbstractScannerResultAdminMixin:
    actions = None
    view_on_site = False
    list_select_related = ('version',)
    raw_id_fields = ('version',)

    ordering = ('-pk',)

    class Media(AMOModelAdmin.Media):
        css = {'all': (vite_asset('css/admin-scanner-results.less'),)}

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
            'version__file',
            'version__addon__authors',
        )

    def get_unfiltered_changelist_params(self):
        """Return query parameters dict used to link to the changelist with
        no filtering applied.

        Needed to link to results from a rule, because the changelist view
        might filter out some results by default."""
        return {
            WithVersionFilter.parameter_name: 'all',
            StateFilter.parameter_name: 'all',
        }

    # Remove the "add" button
    def has_add_permission(self, request):
        return False

    # Read-only mode
    def has_change_permission(self, request, obj=None):
        return False

    # Custom actions
    def has_actions_permission(self, request):
        return acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_RESULTS_EDIT
        )

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
        fields = list(filter(lambda x: x not in to_exclude, fields))
        return fields

    def formatted_addon(self, obj):
        if obj.version:
            return format_html(
                '<table>'
                '  <tr><td>Name:</td><td>{}</td></tr>'
                '  <tr><td>Version:</td><td>{}</td></tr>'
                '  <tr><td>Channel:</td><td>{}</td></tr>'
                '</table>'
                '<br>'
                '<a href="{}">Link to review page</a>',
                obj.version.addon.name,
                obj.version.version,
                obj.version.get_channel_display(),
                # We use the add-on's ID to support deleted add-ons.
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse(
                        'reviewers.review',
                        args=[
                            (
                                'listed'
                                if obj.version.channel == amo.CHANNEL_LISTED
                                else 'unlisted'
                            ),
                            obj.version.addon.id,
                        ],
                    ),
                ),
            )
        return '-'

    formatted_addon.short_description = 'Add-on'

    def authors(self, obj):
        if not obj.version:
            return '-'

        authors = obj.version.addon.authors.all()
        contents = format_html_join(
            '',
            '<li><a href="{}">{}</a></li>',
            (
                (
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('admin:users_userprofile_change', args=(author.pk,)),
                    ),
                    author.email,
                )
                for author in authors
            ),
        )
        return format_html(
            '<ul>{}</ul>'
            '<br>'
            '[<a href="{}?authors__in={}">Other add-ons by these authors</a>]',
            contents,
            urljoin(
                settings.EXTERNAL_SITE_URL,
                reverse('admin:addons_addon_changelist'),
            ),
            ','.join(str(author.pk) for author in authors),
        )

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

    def formatted_created(self, obj):
        if obj.version:
            return obj.version.created.strftime('%Y-%m-%d %H:%M:%S')
        return '-'

    formatted_created.short_description = 'Created'

    def formatted_results(self, obj):
        return format_html('<pre>{}</pre>', obj.get_pretty_results())

    formatted_results.short_description = 'Results'

    def formatted_matched_rules(self, obj):
        info = obj.rule_model._meta.app_label, obj.rule_model._meta.model_name
        rules = (
            [obj.matched_rule]
            if hasattr(obj, 'matched_rule')
            else obj.matched_rules.all()
        )

        return format_html(
            ', '.join(
                [
                    '<a href="{}" title="{}">{} ({})</a>'.format(
                        reverse('admin:%s_%s_change' % info, args=[rule.pk]),
                        str(rule.description),
                        str(rule),
                        rule.get_scanner_display(),
                    )
                    for rule in rules
                ]
            )
        )

    formatted_matched_rules.short_description = 'Matched rules'


class AbstractScannerRuleAdminMixin:
    view_on_site = False

    list_display = (
        '__str__',
        'scanner',
        'action',
        'is_active',
        'exclude_promoted_addons',
    )
    list_filter = ('scanner', 'action', 'is_active')
    fields = (
        'scanner',
        'name',
        'pretty_name',
        'description',
        'action',
        'created',
        'modified',
        'matched_results_link',
        'is_active',
        'definition',
        'exclude_promoted_addons',
    )
    readonly_fields = ('created', 'modified', 'matched_results_link')

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'scanner':
            kwargs['choices'] = (('', '---------'),)
            for key, value in db_field.get_choices():
                if key in [CUSTOMS, YARA, NARC, WEBHOOK]:
                    kwargs['choices'] += ((key, value),)
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    class Media(AMOModelAdmin.Media):
        css = {'all': (vite_asset('css/admin-scanner-rule.less'),)}

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
        counts = obj.results.aggregate(
            addons=Count('version__addon', distinct=True), total=Count('id')
        )
        ResultModel = obj.results.model
        url = reverse(
            'admin:{}_{}_changelist'.format(
                ResultModel._meta.app_label, ResultModel._meta.model_name
            )
        )
        # The parameter name is called matched_rule or matched_rules depending
        # on the model, because one of them is a many to many and the other a
        # simple FK.
        param_name = 'matched_rule%s__id__exact' % (
            's' if obj._meta.get_field('results').many_to_many else ''
        )
        params = {
            param_name: str(obj.pk),
        }
        result_admin = admin.site._registry[ResultModel]
        params.update(result_admin.get_unfiltered_changelist_params())
        return format_html(
            '<a href="{}?{}">{} ({} add-ons)</a>',
            url,
            urlencode(params),
            counts['total'],
            counts['addons'],
        )

    matched_results_link.short_description = 'Matched Results'

    def formatted_definition(self, obj):
        return format_html('<pre>{}</pre>', obj.definition)

    formatted_definition.short_description = 'Definition'


@admin.register(ScannerResult)
class ScannerResultAdmin(AbstractScannerResultAdminMixin, AMOModelAdmin):
    fields = (
        'id',
        'upload',
        'formatted_addon',
        'authors',
        'guid',
        'formatted_scanner',
        'created',
        'state',
        formatted_matched_rules_with_files_and_data,
        'result_actions',
        'formatted_results',
    )
    list_display = (
        'id',
        'formatted_addon',
        'guid',
        'authors',
        'formatted_scanner',
        'formatted_matched_rules',
        'formatted_created',
        'result_actions',
    )
    list_filter = (
        'scanner',
        MatchesFilter,
        StateFilter,
        ('matched_rules', ScannerRuleListFilter),
        WithVersionFilter,
        ExcludeMatchedRulesFilter,
    )
    raw_id_fields = AbstractScannerResultAdminMixin.raw_id_fields + ('upload',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('matched_rules')

    def formatted_scanner(self, obj):
        if obj.scanner == WEBHOOK:
            return f'[webhook] {obj.webhook_event}'
        else:
            return obj.get_scanner_display()

    formatted_scanner.short_description = 'Scanner'

    def safe_referer_redirect(self, request, default_url):
        referer = request.META.get('HTTP_REFERER')
        allowed_hosts = (
            settings.DOMAIN,
            urlparse(settings.EXTERNAL_SITE_URL).netloc,
        )
        if referer and is_safe_url(referer, request, allowed_hosts):
            return redirect(referer)
        return redirect(default_url)

    def handle_true_positive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != 'POST':
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=TRUE_POSITIVE)

        messages.add_message(
            request,
            messages.INFO,
            f'Scanner result {pk} has been marked as true positive.',
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def handle_inconclusive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != 'POST':
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=INCONCLUSIVE)

        messages.add_message(
            request,
            messages.INFO,
            f'Scanner result {pk} has been marked as inconclusive.',
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def handle_false_positive(self, request, pk, *args, **kwargs):
        can_use_actions = self.has_actions_permission(request)
        if not can_use_actions or request.method != 'POST':
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=FALSE_POSITIVE)

        messages.add_message(
            request,
            messages.INFO,
            f'Scanner result {pk} has been marked as false positive.',
        )

        if result.scanner == scanners.CUSTOMS:
            title = f'False positive report for ScannerResult {pk}'
            body = render_to_string(
                'admin/false_positive_report.md', {'result': result, 'YARA': YARA}
            )
            labels = ','.join(
                [
                    # Default label added to all issues
                    'false positive report'
                ]
                + [f'rule: {rule.name}' for rule in result.matched_rules.all()]
            )

            return redirect(
                'https://github.com/{}/issues/new?{}'.format(
                    result.get_git_repository(),
                    urlencode({'title': title, 'body': body, 'labels': labels}),
                )
            )
        else:
            return self.safe_referer_redirect(
                request, default_url='admin:scanners_scannerresult_changelist'
            )

    def handle_revert(self, request, pk, *args, **kwargs):
        is_admin = acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_RESULTS_EDIT
        )
        if not is_admin or request.method != 'POST':
            raise Http404

        result = self.get_object(request, pk)
        result.update(state=UNKNOWN)

        messages.add_message(
            request,
            messages.INFO,
            f'Scanner result {pk} report has been reverted.',
        )

        return self.safe_referer_redirect(
            request, default_url='admin:scanners_scannerresult_changelist'
        )

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        custom_urls = [
            re_path(
                r'^(?P<pk>.+)/report-false-positive/$',
                self.admin_site.admin_view(self.handle_false_positive),
                name='%s_%s_handlefalsepositive' % info,
            ),
            re_path(
                r'^(?P<pk>.+)/report-true-positive/$',
                self.admin_site.admin_view(self.handle_true_positive),
                name='%s_%s_handletruepositive' % info,
            ),
            re_path(
                r'^(?P<pk>.+)/report-inconclusive/$',
                self.admin_site.admin_view(self.handle_inconclusive),
                name='%s_%s_handleinconclusive' % info,
            ),
            re_path(
                r'^(?P<pk>.+)/revert-report/$',
                self.admin_site.admin_view(self.handle_revert),
                name='%s_%s_handlerevert' % info,
            ),
        ]
        return custom_urls + urls

    def result_actions(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        return render_to_string(
            'admin/scannerresult_actions.html',
            {
                'handlefalsepositive_urlname': (
                    'admin:%s_%s_handlefalsepositive' % info
                ),
                'handletruepositive_urlname': ('admin:%s_%s_handletruepositive' % info),
                'handleinconclusive_urlname': ('admin:%s_%s_handleinconclusive' % info),
                'handlerevert_urlname': 'admin:%s_%s_handlerevert' % info,
                'obj': obj,
            },
        )

    result_actions.short_description = 'Actions'
    result_actions.allow_tags = True

    # Remove the "delete" button
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ScannerQueryResult)
class ScannerQueryResultAdmin(AbstractScannerResultAdminMixin, AMOModelAdmin):
    fields = (
        'id',
        'formatted_addon',
        'authors',
        'guid',
        'scanner',
        'created',
        formatted_matched_rules_with_files_and_data,
        'formatted_results',
    )
    raw_id_fields = ('version',)
    list_display_links = None
    list_display = (
        'addon_name',
        'guid',
        'addon_adi',
        'formatted_channel',
        'version_number',
        'formatted_created',
        'is_file_signed',
        'was_blocked',
        'was_promoted',
        'authors',
        'formatted_matched_rules',
        'matching_filenames',
        'download',
    )
    list_filter = (
        ('matched_rule', ScannerRuleListFilter),
        ('version__channel', VersionChannelFilter),
        ('version__created', VersionCreatedFilter),
        ('version__addon__status', AddonStatusFilter),
        ('version__addon__created', AddonCreatedFilter),
        ('version__addon__last_updated', AddonLastUpdatedFilter),
        ('version__addon__disabled_by_user', AddonVisibilityFilter),
        ('version__addon__average_daily_users', AddonAverageDailyUsers),
        ('version__file__status', FileStatusFilter),
        ('version__file__is_signed', FileIsSignedFilter),
        ('was_blocked', admin.BooleanFieldListFilter),
        ('was_promoted', admin.BooleanFieldListFilter),
    )
    list_select_related = AbstractScannerResultAdminMixin.list_select_related + (
        'matched_rule',
    )

    ordering = ('version__addon_id', 'version__channel', 'version__created')

    class Media(AbstractScannerResultAdminMixin.Media):
        js = (vite_asset('js/admin-scanner-query-result.js'),)

    def addon_name(self, obj):
        # Custom, simpler implementation to go with add-on grouping: the
        # version number and version channel are not included - they are
        # displayed as separate columns.
        if obj.version:
            return obj.version.addon.name
        return '-'

    addon_name.short_description = 'Add-on'

    def addon_adi(self, obj):
        if obj.version:
            return obj.version.addon.average_daily_users
        return '-'

    addon_adi.admin_order_field = 'version__addon__average_daily_users'

    def formatted_channel(self, obj):
        if obj.version:
            return format_html(
                '<a href="{}">{}</a>',
                # We use the add-on's ID to support deleted add-ons.
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse(
                        'reviewers.review',
                        args=[
                            (
                                'listed'
                                if obj.version.channel == amo.CHANNEL_LISTED
                                else 'unlisted'
                            ),
                            obj.version.addon.id,
                        ],
                    ),
                ),
                obj.version.get_channel_display(),
            )
        return '-'

    def version_number(self, obj):
        if obj.version:
            return obj.version.version
        return '-'

    version_number.short_description = 'Version'

    def is_file_signed(self, obj):
        if obj.version and obj.version.file:
            return obj.version.file.is_signed
        return False

    is_file_signed.short_description = 'Is Signed'
    is_file_signed.boolean = True

    def get_unfiltered_changelist_params(self):
        return {}

    def matching_filenames(self, obj):
        return formatted_matched_rules_with_files_and_data(
            obj, template_name='formatted_matching_files'
        )

    def download(self, obj):
        if obj.version and obj.version.file:
            return format_html(
                '<a href="{}">{}</a>',
                obj.version.file.get_absolute_url(attachment=True),
                obj.version.file.pk,
            )
        return '-'

    def has_actions_permission(self, request):
        return acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        )


@admin.register(ScannerRule)
class ScannerRuleAdmin(AbstractScannerRuleAdminMixin, AMOModelAdmin):
    pass


@admin.register(ScannerQueryRule)
class ScannerQueryRuleAdmin(AbstractScannerRuleAdminMixin, AMOModelAdmin):
    list_display = (
        '__str__',
        'scanner',
        'run_on_disabled_addons',
        'run_on_specific_channel',
        'run_on_current_version_only',
        'exclude_promoted_addons',
        'created',
        'state_with_actions',
        'completion_rate',
        'matched_results_link',
    )
    list_filter = (
        'scanner',
        'state',
    )
    fields = (
        'scanner',
        'run_on_disabled_addons',
        'run_on_specific_channel',
        'run_on_current_version_only',
        'exclude_promoted_addons',
        'state_with_actions',
        'name',
        'pretty_name',
        'description',
        'created',
        'modified',
        'completion_rate',
        'matched_results_link',
        'definition',
    )
    readonly_fields = (
        'completion_rate',
        'created',
        'modified',
        'matched_results_link',
        'state_with_actions',
    )

    def change_view(self, request, *args, **kwargs):
        kwargs['extra_context'] = kwargs.get('extra_context') or {}
        kwargs['extra_context']['hide_action_buttons'] = not acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        )
        return super().change_view(request, *args, **kwargs)

    def changelist_view(self, request, *args, **kwargs):
        kwargs['extra_context'] = kwargs.get('extra_context') or {}
        kwargs['extra_context']['hide_action_buttons'] = not acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        )
        return super().changelist_view(request, *args, **kwargs)

    def has_change_permission(self, request, obj=None):
        if obj and obj.state != NEW:
            return False
        return super().has_change_permission(request, obj=obj)

    def handle_run(self, request, pk, *args, **kwargs):
        is_admin = acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        )
        if not is_admin or request.method != 'POST':
            raise Http404

        rule = self.get_object(request, pk)
        try:
            # SCHEDULED is a transitional state that allows us to update the UI
            # right away before redirecting. Once it starts being processed the
            # task will switch it to RUNNING.
            rule.change_state_to(SCHEDULED)
            run_scanner_query_rule.delay(rule.pk)

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
                    rule.pk, rule.get_state_display()
                ),
            )

        return redirect('admin:scanners_scannerqueryrule_changelist')

    def handle_abort(self, request, pk, *args, **kwargs):
        is_admin = acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        )
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
                f'Scanner Query Rule {rule.pk} is being aborted.',
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
            re_path(
                r'^(?P<pk>.+)/abort/$',
                self.admin_site.admin_view(self.handle_abort),
                name='%s_%s_handle_abort' % info,
            ),
            re_path(
                r'^(?P<pk>.+)/run/$',
                self.admin_site.admin_view(self.handle_run),
                name='%s_%s_handle_run' % info,
            ),
        ]
        return custom_urls + urls

    def state_with_actions(self, obj):
        return render_to_string(
            'admin/scannerqueryrule_state_with_actions.html',
            {
                'obj': obj,
                'COMPLETED': COMPLETED,
                'NEW': NEW,
                'RUNNING': RUNNING,
            },
        )

    state_with_actions.short_description = 'State'
    state_with_actions.allow_tags = True

    def get_deleted_objects(self, objs, request):
        """
        Hook used by Django admin to display objects that are about to be
        deleted (purely for information purposes).

        https://docs.djangoproject.com/en/4.2/ref/contrib/admin/
        #django.contrib.admin.ModelAdmin.get_deleted_objects

        Return a tuple of (deleted_objects, model_count, perms_needed, protected).
        """
        # Original django implementation would try to display all related
        # models, we avoid that because there can be too many, and it's obvious
        # that deleting a query rule will delete the query results anyway.
        deleted_objects = [
            capfirst(f'{self.model._meta.verbose_name}: {obj}') for obj in objs
        ]

        # Again original django implementation would count the related objects
        # but we simplify to avoid expensive queries.
        model_count = {self.model._meta.verbose_name_plural: len(objs)}

        # We know the user deleting this shouldn't need extra permissions from
        # related objects, so we don't have anything to display there.
        perms_needed = set()

        # Similarly we know there won't be any special objects that won't be
        # deleted, so we don't have anything to display there either.
        protected = []

        return (deleted_objects, model_count, perms_needed, protected)


class ScannerWebhookEventInline(admin.StackedInline):
    model = ScannerWebhookEvent
    view_on_site = False
    extra = 0


@admin.register(ScannerWebhook)
class ScannerWebhookAdmin(AMOModelAdmin):
    view_on_site = False

    inlines = [ScannerWebhookEventInline]

    list_display = (
        'name',
        'url',
        'formatted_events_list',
        'is_active',
    )
    readonly_fields = ('service_account',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('scannerwebhookevent_set')

    def formatted_events_list(self, obj):
        return ', '.join(
            [
                WEBHOOK_EVENTS.get(item.event, '(unknown)')
                for item in obj.scannerwebhookevent_set.all()
            ]
        )

    formatted_events_list.short_description = 'Events'

    def service_account(self, obj):
        try:
            user = UserProfile.objects.get_service_account(
                name=obj.service_account_name
            )
        except UserProfile.DoesNotExist:
            return '(will be automatically created)'

        return format_html(
            '<a href="{}">{}</a>',
            urljoin(
                settings.EXTERNAL_SITE_URL,
                reverse('admin:users_userprofile_change', args=(user.pk,)),
            ),
            user.username,
        )

    def save_model(self, request, obj, form, change):
        # First save the model.
        super().save_model(request, obj, form, change)

        if not change:
            # Display the JWT keys only once on creation.
            try:
                user = UserProfile.objects.get_service_account(
                    name=obj.service_account_name
                )
                api_key = APIKey.get_jwt_key(user=user)
                messages.add_message(
                    request,
                    messages.INFO,
                    format_html(
                        'Please note the JWT keys for the service account '
                        '"<a href="{}">{}</a>":'
                        '<br><br>'
                        '<code>{}</code>'
                        '<br>'
                        '<code>{}</code>',
                        urljoin(
                            settings.EXTERNAL_SITE_URL,
                            reverse('admin:users_userprofile_change', args=(user.pk,)),
                        ),
                        user.username,
                        api_key.key,
                        api_key.secret,
                    ),
                )
            except Exception:
                pass
