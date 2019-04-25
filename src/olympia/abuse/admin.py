from collections import OrderedDict

from django import forms
from django.contrib import admin
from django.db.models import Count, Q, Prefetch
from django.utils.translation import ugettext

from rangefilter.filter import (
    DateRangeFilter as DateRangeFilterBase,
)

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.translations.utils import truncate_text

from .models import AbuseReport


class AbuseReportTypeFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = ugettext('type')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'type'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return (
            ('user', ugettext('Users')),
            ('addon', ugettext('Addons')),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'user':
            return queryset.filter(user__isnull=False)
        elif self.value() == 'addon':
            return queryset.filter(Q(addon__isnull=False) |
                                   Q(guid__isnull=False))
        return queryset


class FakeChoicesMixin(object):
    def choices(self, changelist):
        """
        Fake choices method (we don't need one, we don't really have choices
        for this filter, it's an input widget) that fetches the params and the
        current values for other filters, so that we can feed that into
        the form that our template displays.

        (We don't control the data passed down to the template, so re-using
        this one is our only option)
        """
        # Grab search query parts and filter query parts as tuples of tuples.
        search_query_parts = (
            ((admin.views.main.SEARCH_VAR, changelist.query),)
        ) if changelist.query else ()
        filters_query_parts = tuple(
            (k, v)
            for k, v in changelist.get_filters_params().items()
            if k not in self.expected_parameters()
        )
        # Assemble them into a `query_parts` property on a unique fake choice.
        all_choice = next(super().choices(changelist))
        all_choice['query_parts'] = search_query_parts + filters_query_parts
        yield all_choice


class MinimumReportsCountFilter(FakeChoicesMixin, admin.SimpleListFilter):
    """
    Custom filter for minimum reports count param.

    Does *not* do the actual filtering of the queryset, as it needs to be done
    with an aggregate query after all filters have been applied. That part is
    implemented in the model admin, see AbuseReportAdmin.get_search_results().

    Needs FakeChoicesMixin for the fake choices the template will be using.

    Original idea:
    https://hakibenita.com/how-to-add-a-text-filter-to-django-admin
    """
    template = 'admin/abuse/abusereport/minimum_reports_count_filter.html'
    title = ugettext('minimum reports count (grouped by guid)')
    parameter_name = 'minimum_reports_count'

    def lookups(self, request, model_admin):
        """
        Fake lookups() method required to show the filter.
        """
        return ((),)

    def queryset(self, request, queryset):
        return queryset


class HTML5DateInput(forms.DateInput):
    format_key = 'DATE_INPUT_FORMATS'
    input_type = 'date'


class DateRangeFilter(FakeChoicesMixin, DateRangeFilterBase):
    """
    Custom rangefilter.filters.DateTimeRangeFilter class that uses HTML5
    widgets and a template without the need for inline CSS/JavaScript.

    Needs FakeChoicesMixin for the fake choices the template will be using (the
    upstream implementation depends on JavaScript for this).
    """
    template = 'admin/abuse/abusereport/date_range_filter.html'
    title = ugettext('creation date')

    def _get_form_fields(self):
        return OrderedDict((
            (self.lookup_kwarg_gte, forms.DateField(
                label='From',
                widget=HTML5DateInput(),
                localize=True,
                required=False
            )),
            (self.lookup_kwarg_lte, forms.DateField(
                label='To',
                widget=HTML5DateInput(),
                localize=True,
                required=False
            )),
        ))

    def choices(self, changelist):
        # We want a fake 'All' choice as per FakeChoicesMixin, but as of 0.3.15
        # rangefilter's implementation doesn't bother setting the selected
        # property, and our mixin calls super(), so we have to do it here.
        all_choice = next(super().choices(changelist))
        all_choice['selected'] = not any(self.used_parameters)
        yield all_choice


class AbuseReportAdmin(admin.ModelAdmin):
    actions = ('delete_selected', 'mark_as_valid', 'mark_as_suspicious')
    date_hierarchy = 'modified'
    list_display = ('target_name', 'guid', 'type', 'state', 'distribution',
                    'reason', 'message_excerpt', 'created')
    list_filter = (
        AbuseReportTypeFilter,
        'state',
        'reason',
        ('created', DateRangeFilter),
        MinimumReportsCountFilter,
    )
    list_select_related = ('user',)  # For `addon` see get_queryset() below.
    # Shouldn't be needed because those fields should all be readonly, but just
    # in case we change our mind, FKs should be raw id fields as usual in our
    # admin tools.
    raw_id_fields = ('addon', 'user', 'reporter')
    # All fields except state must be readonly - the submitted data should
    # not be changed, only the state for triage.
    readonly_fields = list(
        f.name for f in AbuseReport._meta.fields if f.name != 'state')
    search_fields = (
        'addon__name__localized_string', 'addon__slug', 'addon_name', 'guid',
        'message')

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not acl.action_allowed(request, amo.permissions.ABUSEREPORTS_EDIT):
            # You need AbuseReports:Edit for the extra actions.
            actions.pop('mark_as_valid')
            actions.pop('mark_as_suspicious')
        return actions

    def get_search_results(self, request, qs, search_term):
        """
        Custom get_search_results() method that handles minimum_reports_count.
        """
        minimum_reports_count = request.GET.get('minimum_reports_count')
        if minimum_reports_count:
            # minimum_reports_count has its own custom filter class but the
            # filtering is actually done here, because it needs to happen after
            # all other filters have been applied in order for the aggregate
            # queryset to be correct.
            guids = (qs.values_list('guid', flat=True)
                       .filter(guid__isnull=False)
                       .annotate(Count('guid'))
                       .filter(guid__count__gte=minimum_reports_count)
                       .order_by())
            qs = qs.filter(guid__in=list(guids))
        qs, use_distinct = super().get_search_results(request, qs, search_term)
        return qs, use_distinct

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Minimize number of queries : for users linked to abuse reports, we
        # don't have transformers, so we can directly make a JOIN, and that's
        # taken care of by list_select_related. For addons, we want the
        # translations transformer, so the most efficient way to load them is
        # through prefetch_related() + only_translations() (we don't care about
        # the other transforms).
        return qs.prefetch_related(
            Prefetch(
                'addon', queryset=Addon.objects.all().only_translations()),
        )

    def target_name(self, obj):
        name = obj.target.name if obj.target else obj.addon_name
        return '%s %s' % (name, obj.addon_version or '')
    target_name.short_description = ugettext('Target')

    def distribution(self, obj):
        return obj.get_addon_signature_display() if obj.addon_signature else ''
    distribution.short_description = ugettext('Distribution')

    def reporter_country(self, obj):
        return obj.country_code
    reporter_country.short_description = ugettext("Reporter's country")

    def message_excerpt(self, obj):
        return truncate_text(obj.message, 140)[0] if obj.message else ''
    message_excerpt.short_description = ugettext('Message excerpt')

    def mark_as_valid(self, request, qs):
        for obj in qs:
            obj.update(state=AbuseReport.STATES.VALID)
        self.message_user(
            request,
            ugettext(
                'The %d selected reports have been marked as valid.' % (
                    qs.count())))
    mark_as_valid.short_description = 'Mark selected abuse reports as valid'

    def mark_as_suspicious(self, request, qs):
        for obj in qs:
            obj.update(state=AbuseReport.STATES.SUSPICIOUS)
        self.message_user(
            request,
            ugettext(
                'The %d selected reports have been marked as suspicious.' % (
                    qs.count())))
    mark_as_suspicious.short_description = (
        ugettext('Mark selected abuse reports as suspicious'))


admin.site.register(AbuseReport, AbuseReportAdmin)
