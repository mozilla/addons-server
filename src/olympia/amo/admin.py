import functools
import ipaddress
import operator
from collections import OrderedDict

from django import forms
from django.contrib import admin
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.utils import reverse_field_path
from django.contrib.admin.views.main import (
    ERROR_FLAG,
    PAGE_VAR,
    SEARCH_VAR,
    ChangeList,
    ChangeListSearchForm,
)
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import InvalidPage
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.http.request import QueryDict
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from django_vite.templatetags.django_vite import vite_hmr_client
from rangefilter.filters import (
    DateRangeFilter as DateRangeFilterBase,
    NumericRangeFilter as NumericRangeFilterBase,
)

from olympia.activity.models import IPLog
from olympia.amo.models import GroupConcat, Inet6Ntoa
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.constants.activity import LOG_BY_ID

from .models import FakeEmail


class AMOModelAdminChangeListSearchForm(ChangeListSearchForm):
    def clean(self):
        self.cleaned_data = super().clean()
        search_term = self.cleaned_data[SEARCH_VAR]
        if ',' in search_term:
            self.cleaned_data[SEARCH_VAR] = ','.join(
                term.strip() for term in search_term.split(',') if term.strip()
            )
        return self.cleaned_data


class AMOModelAdminChangeList(ChangeList):
    """Custom ChangeList companion for AMOModelAdmin, allowing to have a custom
    search form and providing support for query string containing the same
    parameter multiple times, as well as a separate count_queryset property
    to use a different, leaner queryset when figuring out the count for
    pagination purposes."""

    search_form_class = AMOModelAdminChangeListSearchForm

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        # django's ChangeList does:
        # self.params = dict(request.GET.items())
        # But we want to keep a QueryDict to not lose parameters present
        # multiple times.
        self.params = request.GET.copy()
        # We have to re-apply what django does to self.params:
        if PAGE_VAR in self.params:
            del self.params[PAGE_VAR]
        if ERROR_FLAG in self.params:
            del self.params[ERROR_FLAG]

    def get_results_count(self, request):
        """Return the count for the number of results for this changelist.

        Separate custom method in order to exclude display only annotations,
        optimizing database performance (at the expense of rebuilding the
        queryset a second time).
        """
        old_root_queryset = self.root_queryset._clone()
        self.root_queryset = self.root_queryset.alias(for_count=models.Value(True))
        # get_queryset() uses self.root_queryset, which we've now annotated.
        queryset = self.get_queryset(request)
        # Revert root_queryset to the non-annotated original one.
        self.root_queryset = old_root_queryset
        return queryset.count()

    def get_ordering(self, request, queryset):
        # Don't try to order results when counting, the annotations the
        # ordering depends on do not exist and it's pointless anyway.
        if 'for_count' in queryset.query.annotations:
            return []
        return super().get_ordering(request, queryset)

    def get_filters(self, request):
        # Cache added because our custom get_results()/get_results_count() will
        # cause get_filters() to be called twice, and it can generate some db
        # queries.
        if not hasattr(self, '_filters_cache'):
            self._filters_cache = super().get_filters(request)
        return self._filters_cache

    def get_results(self, request):
        # Copied from django, including comments. The only change is the
        # addition of the get_results_count() method that overrides the
        # paginator count.

        paginator = self.model_admin.get_paginator(
            request, self.queryset, self.list_per_page
        )
        paginator.count = self.get_results_count(request)
        # Get the number of objects, with admin filters applied.
        result_count = paginator.count

        # Get the total number of objects, with no admin filters applied.
        if self.model_admin.show_full_result_count:
            full_result_count = self.root_queryset.count()
        else:
            full_result_count = None
        can_show_all = result_count <= self.list_max_show_all
        multi_page = result_count > self.list_per_page

        # Get the list of objects to display on this page.
        if (self.show_all and can_show_all) or not multi_page:
            result_list = self.queryset._clone()
        else:
            try:
                result_list = paginator.page(self.page_num).object_list
            except InvalidPage as exc:
                raise IncorrectLookupParameters from exc

        self.result_count = result_count
        self.show_full_result_count = self.model_admin.show_full_result_count
        # Admin actions are shown if there is at least one entry
        # or if entries are not counted because show_full_result_count is disabled
        self.show_admin_actions = not self.show_full_result_count or bool(
            full_result_count
        )
        self.full_result_count = full_result_count
        self.result_list = result_list
        self.can_show_all = can_show_all
        self.multi_page = multi_page
        self.paginator = paginator

    def apply_select_related(self, qs):
        # Only apply select_related() if we're not doing a COUNT(*) query.
        # When we really want to force a select_related to always take place it
        # can be added to the get_queryset() method of the ModelAdmin.
        if 'for_count' not in qs.query.annotations:
            qs = super().apply_select_related(qs)
            # Annotations that we don't want to apply to the count(*) query are
            # added to our special get_queryset_annotations() method.
            if hasattr(self.model_admin, 'get_queryset_annotations'):
                qs = qs.annotate(**self.model_admin.get_queryset_annotations())
        return qs

    def get_query_string(self, new_params=None, remove=None):
        # django's ChangeList.get_query_string() doesn't respect parameters
        # that are present multiple times, e.g. ?foo=1&foo=2 - it expects
        # self.params to be a dict.
        # We set self.params to a QueryDict in __init__, and if it is a
        # QueryDict, then we use a copy of django's implementation with just
        # the last line changed to p.urlencode().
        # We have to keep compatibility for when self.params is not a QueryDict
        # yet, because this method is called once in __init__() before we have
        # the chance to set self.params to a QueryDict. It doesn't matter for
        # our use case (it's to generate an url with no filters at all) but we
        # have to support it.
        if not isinstance(self.params, QueryDict):
            return super().get_query_string(new_params=new_params, remove=remove)
        if new_params is None:
            new_params = {}
        if remove is None:
            remove = []
        p = self.params.copy()
        for r in remove:
            for k in list(p):
                if k.startswith(r):
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            else:
                p[k] = v
        return '?%s' % p.urlencode()


class AMOModelAdmin(admin.ModelAdmin):
    class Media:
        js = (vite_hmr_client(), vite_asset('js/admin.js'))
        css = {'all': (vite_asset('css/admin.less'),)}

    # Classes that want to implement search by ip can override these if needed.
    search_by_ip_actions = ()  # Deactivated by default.
    search_by_ip_activity_accessor = 'activitylog'
    search_by_ip_activity_reverse_accessor = 'activity_log__user'
    # get_search_results() below searches using `IPLog`. It sets an annotation
    # that we can then use in the custom `known_ip_adresses` method referenced
    # in the line below, which is added to the` list_display` fields for IP
    # searches.
    extra_list_display_for_ip_searches = ('known_ip_adresses',)
    # We rarely care about showing this: it's the full count of the number of
    # objects for this model in the database, unfiltered. It does an extra
    # COUNT() query, so avoid it by default.
    show_full_result_count = False

    def get_changelist(self, request, **kwargs):
        return AMOModelAdminChangeList

    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        extra_context.update(
            {
                'search_id_field': self.get_search_id_field(request),
                'search_fields': self.get_search_fields(request),
                'search_by_ip_actions_names': [
                    LOG_BY_ID[action].__name__ for action in self.search_by_ip_actions
                ],
                'minimum_search_terms_to_search_by_id': (
                    self.minimum_search_terms_to_search_by_id
                ),
            }
        )
        return super().changelist_view(request, extra_context=extra_context)

    def get_search_id_field(self, request):
        """
        Return the field to use when all search terms are numeric.

        Default is to return pk, but in some cases it'll make more sense to
        return a foreign key.
        """
        return 'pk'

    def get_search_query(self, request):
        # We don't have access to the _search_form instance the ChangeList
        # creates, so make our own just for this method to grab the cleaned
        # search term.
        search_form = AMOModelAdminChangeListSearchForm(request.GET)
        return (
            search_form.cleaned_data.get(SEARCH_VAR) if search_form.is_valid() else None
        )

    def get_list_display(self, request):
        """Get fields to use for displaying changelist."""
        list_display = super().get_list_display(request)
        if (
            self.search_by_ip_actions
            and (search_term := self.get_search_query(request))
            and self.ip_addresses_and_networks_from_query(search_term)
            and not set(list_display).issuperset(
                self.extra_list_display_for_ip_searches
            )
        ):
            return (*list_display, *self.extra_list_display_for_ip_searches)
        return list_display

    def lookup_spawns_duplicates(self, opts, lookup_path):
        """
        Return True if 'distinct()' should be used to query the given lookup
        path. Used by get_search_results() as a replacement of the version used
        by django, which doesn't consider our translation fields as needing
        distinct (but they do).
        """
        # The utility function was admin.utils.lookup_needs_distinct in django3.2;
        # it was renamed to admin.utils.lookup_spawns_duplicates in django4.0
        lookup_function = (
            getattr(admin.utils, 'lookup_spawns_duplicates', None)
            or admin.utils.lookup_needs_distinct
        )
        rval = lookup_function(opts, lookup_path)
        lookup_fields = lookup_path.split(LOOKUP_SEP)
        # Not pretty but looking up the actual field would require truly
        # resolving the field name, walking to any relations we find up until
        # the last one, that would be a lot of work for a simple edge case.
        if any(
            field_name in lookup_fields
            for field_name in ('localized_string', 'localized_string_clean')
        ):
            rval = True
        return rval

    def ip_addresses_and_networks_from_query(self, search_term):
        # Caller should already have cleaned up search_term at this point,
        # removing whitespace etc if there is a comma separating multiple
        # terms.
        search_terms = search_term.split(',')
        ips = []
        networks = []
        for term in search_terms:
            # If term is a number, skip trying to recognize an IP address
            # entirely, because ip_address() is able to understand IP addresses
            # as integers, and we don't want that, it's likely an user ID.
            if term.isdigit():
                return None
            # Is the search term an IP ?
            try:
                ips.append(ipaddress.ip_address(term))
                continue
            except ValueError:
                pass
            # Is the search term a network ?
            try:
                networks.append(ipaddress.ip_network(term))
                continue
            except ValueError:
                pass
            # Is the search term an IP range ?
            if term.count('-') == 1:
                try:
                    networks.extend(
                        ipaddress.summarize_address_range(
                            *(ipaddress.ip_address(i.strip()) for i in term.split('-'))
                        )
                    )
                    continue
                except (ValueError, TypeError):
                    pass
            # That search term doesn't look like an IP, network or range, so
            # we're not doing an IP search.
            return None
        return {'ips': ips, 'networks': networks}

    def get_activity_accessor_prefix(self):
        return (
            f'{self.search_by_ip_activity_accessor}__'
            if self.search_by_ip_activity_accessor
            else ''
        )

    def get_queryset_with_related_ips(self, request, queryset, ips_and_networks):
        condition = models.Q()
        if ips_and_networks is not None:
            if ips_and_networks['ips']:
                # IPs search can be implemented in a single __in=() query.
                arg = (
                    self.get_activity_accessor_prefix() + 'iplog__ip_address_binary__in'
                )
                condition |= models.Q(**{arg: ips_and_networks['ips']})
            if ips_and_networks['networks']:
                # Networks search need one __range conditions for each network.
                arg = (
                    self.get_activity_accessor_prefix()
                    + 'iplog__ip_address_binary__range'
                )
                for network in ips_and_networks['networks']:
                    condition |= models.Q(**{arg: (network[0], network[-1])})
        if condition or (
            'known_ip_adresses' in self.list_display
            and 'for_count' not in queryset.query.annotations
        ):
            queryset = queryset.annotate(
                activity_ips=GroupConcat(
                    Inet6Ntoa(
                        self.get_activity_accessor_prefix() + 'iplog__ip_address_binary'
                    ),
                    distinct=True,
                )
            )
        if condition:
            arg = self.get_activity_accessor_prefix() + 'action__in'
            condition &= models.Q(**{arg: self.search_by_ip_actions})
            # When searching, we want to duplicate the joins against
            # activitylog + iplog so that one is used for the group concat
            # showing all IPs for activities related to that object and another
            # for the search results. Django doesn't let us do that out of the
            # box, but through FilteredRelation we can force it...
            aliases = {
                # Add an alias for {get_activity_accessor_prefix()}__iplog__id
                # so that we can apply a filter on the specific JOIN that will be
                # used to grab the IPs through GroupConcat to help MySQL optimizer
                # remove non relevant activities from the DISTINCT bit.
                'activity_ips_ids': models.F(
                    self.get_activity_accessor_prefix() + 'iplog__id'
                ),
                'activitylog_filtered': models.FilteredRelation(
                    self.get_activity_accessor_prefix() + 'iplog', condition=condition
                ),
            }
            queryset = queryset.alias(**aliases).filter(
                activity_ips_ids__isnull=False,
                activitylog_filtered__isnull=False,
            )
        # A GROUP_BY will already have been applied thanks to our annotations
        # so we can let django know there won't be any duplicates and avoid
        # doing a DISTINCT.
        may_have_duplicates = False
        return queryset, may_have_duplicates

    def get_search_results(self, request, queryset, search_term):
        """
        Return a tuple containing a queryset to implement the search,
        and a boolean indicating if the results may contain duplicates.

        Originally copied from Django's, but with the following differences:
        - The operator joining the query parts is dynamic: if the search term
          contain a comma and no space, then the comma is used as the separator
          instead, and the query parts are joined by OR, not AND, allowing
          admins to search by a list of ids, emails or usernames and find all
          objects in that list.
        - If the search terms are all numeric and there is more than one, then
          we also restrict the fields we search to the one returned by
          get_search_id_field(request) using a __in ORM lookup directly.
        - If the search terms are all IP addresses, a special search for
          objects matching those IPs is triggered
        - If the queryset has a `for_count` property, then we use that to do
          some optimizations, removing annotations that are only needed for
          display purposes.
        """

        # Apply keyword searches.
        def construct_search(field_name):
            if field_name.startswith('^'):
                return '%s__istartswith' % field_name[1:]
            elif field_name.startswith('='):
                return '%s__iexact' % field_name[1:]
            elif field_name.startswith('@'):
                return '%s__icontains' % field_name[1:]
            # Use field_name if it includes a lookup.
            opts = queryset.model._meta
            lookup_fields = field_name.split(models.constants.LOOKUP_SEP)
            # Go through the fields, following all relations.
            prev_field = None
            for path_part in lookup_fields:
                if path_part == 'pk':
                    path_part = opts.pk.name
                try:
                    field = opts.get_field(path_part)
                except FieldDoesNotExist:
                    # Use valid query lookups.
                    if prev_field and prev_field.get_lookup(path_part):
                        return field_name
                else:
                    prev_field = field
                    if hasattr(field, 'get_path_info'):
                        # Update opts to follow the relation.
                        opts = field.get_path_info()[-1].to_opts
            # Otherwise, use the field with icontains.
            return '%s__icontains' % field_name

        if self.search_by_ip_actions:
            ips_and_networks = self.ip_addresses_and_networks_from_query(search_term)
            # If self.search_by_ip_actions is truthy, then we can call
            # get_queryset_with_related_ips(), which will add IP
            # annotations if needed (either because we're doing an IP search
            # or because the known_ip_addresses field is in list_display)
            queryset, may_have_duplicates = self.get_queryset_with_related_ips(
                request, queryset, ips_and_networks
            )
            # ... We can return here early if we were indeed searching by IP.
            if ips_and_networks:
                return queryset, may_have_duplicates
        else:
            may_have_duplicates = False

        search_fields = self.get_search_fields(request)
        filters = []
        joining_operator = operator.and_
        if not (search_fields and search_term):
            # return early if we have nothing special to do
            return queryset, may_have_duplicates
        # Do our custom logic if a `,` is present. Note that our custom search
        # form (AMOModelAdminChangeListSearchForm) does some preliminary
        # cleaning when it sees a comma, trimming whitespace around each term.
        if ',' in search_term:
            separator = ','
            joining_operator = operator.or_
        else:
            separator = None
        # We support `*` as a wildcard character for our `__like` lookups.
        search_term = search_term.replace('*', '%')
        search_terms = search_term.split(separator)
        if (
            (search_id_field := self.get_search_id_field(request))
            and len(search_terms) >= self.minimum_search_terms_to_search_by_id
            and all(term.isnumeric() for term in search_terms)
        ):
            # if we have at least minimum_search_terms_to_search_by_id terms
            # they are all numeric, we're doing a bulk id search
            queryset = queryset.filter(**{f'{search_id_field}__in': search_terms})
        else:
            orm_lookups = [
                construct_search(str(search_field)) for search_field in search_fields
            ]
            for bit in search_terms:
                or_queries = [
                    models.Q(**{orm_lookup: bit}) for orm_lookup in orm_lookups
                ]

                q_for_this_term = models.Q(functools.reduce(operator.or_, or_queries))
                filters.append(q_for_this_term)

            may_have_duplicates |= any(
                # Use our own lookup_spawns_duplicates(), not django's.
                self.lookup_spawns_duplicates(self.opts, search_spec)
                for search_spec in orm_lookups
            )

            if filters:
                queryset = queryset.filter(functools.reduce(joining_operator, filters))
        return queryset, may_have_duplicates

    @admin.display(ordering='activity_ips', description='IP addresses')
    def known_ip_adresses(self, obj):
        # activity_ips is an annotation added by get_search_results() above
        # thanks to a GROUP_CONCAT. If present, use that (avoiding making
        # extra queries for each row of results), otherwise, look where
        # appropriate.
        unset = object()
        activity_ips = getattr(obj, 'activity_ips', unset)
        if activity_ips is not unset:
            # The GroupConcat value is a comma seperated string of the ip
            # addresses (already converted to string thanks to INET6_NTOA,
            # except if there was nothing to find, then it would be None)
            ip_addresses = set((activity_ips or '').split(','))
        else:
            arg = self.search_by_ip_activity_reverse_accessor
            ip_addresses = set(
                IPLog.objects.filter(**{arg: obj})
                .values_list('ip_address_binary', flat=True)
                .order_by()
                .distinct()
            )

        activities_changelist = reverse('admin:activity_activitylog_changelist')
        contents = format_html_join(
            '',
            '<li><a href="{}?q={}">{}</a></li>',
            sorted((activities_changelist, str(i), str(i)) for i in ip_addresses),
        )
        return format_html('<ul>{}</ul>', contents)

    # Triggering a search by id only isn't always what the admin wants for an
    # all numeric query, but on the other hand is a nice optimization.
    # The default is 2 so that if there is a field in search_fields for which
    # it makes sense to search using a single numeric term, that still works,
    # the id-only search is only triggered for 2 or more terms. This should be
    # overriden by ModelAdmins where it makes sense to do so.
    minimum_search_terms_to_search_by_id = 2


@admin.register(FakeEmail)
class FakeEmailAdmin(admin.ModelAdmin):
    list_display = (
        'created',
        'message',
    )
    actions = ['delete_selected']
    view_on_site = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class FakeChoicesMixin:
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
            (((admin.views.main.SEARCH_VAR, changelist.query),))
            if changelist.query
            else ()
        )
        filters_query_parts = tuple(
            (k, v)
            for k, v in changelist.get_filters_params().items()
            if k not in self.expected_parameters()
        )
        # Assemble them into a `query_parts` property on a unique fake choice.
        # For forms that don't display the 'All' link, also export the other
        # params as a querydict.
        all_choice = next(super().choices(changelist))
        all_choice.update(
            {
                'query_parts': search_query_parts + filters_query_parts,
                'params': QueryDict(
                    changelist.get_query_string(remove=self.expected_parameters())[1:]
                ),
            }
        )
        yield all_choice


class HTML5DateInput(forms.DateInput):
    format_key = 'DATE_INPUT_FORMATS'
    input_type = 'date'


class HTML5DateTimeInput(forms.DateTimeInput):
    format_key = 'DATETIME_INPUT_FORMATS'
    input_type = 'datetime-local'


class DateRangeFilter(FakeChoicesMixin, DateRangeFilterBase):
    """
    Custom rangefilter.filters.DateTimeRangeFilter class that uses HTML5
    widgets and a template without the need for inline CSS/JavaScript.

    Needs FakeChoicesMixin for the fake choices the template will be using (the
    upstream implementation depends on inline JavaScript for this, which we
    want to avoid).
    """

    template = 'admin/amo/date_range_filter.html'
    title = 'creation date'
    widget = HTML5DateInput

    def _get_form_fields(self):
        return OrderedDict(
            (
                (
                    self.lookup_kwarg_gte,
                    forms.DateField(
                        label='From',
                        widget=self.widget(),
                        localize=True,
                        required=False,
                    ),
                ),
                (
                    self.lookup_kwarg_lte,
                    forms.DateField(
                        label='To',
                        widget=self.widget(),
                        localize=True,
                        required=False,
                    ),
                ),
            )
        )

    def choices(self, changelist):
        # We want a fake 'All' choice as per FakeChoicesMixin, but as of 0.3.15
        # rangefilter's implementation doesn't bother setting the selected
        # property, and our mixin calls super(), so we have to do it here.
        all_choice = next(super().choices(changelist))
        all_choice['selected'] = not any(self.used_parameters)
        yield all_choice


class NumericRangeFilter(FakeChoicesMixin, NumericRangeFilterBase):
    """
    Custom rangefilter.filters.NumericRangeFilter class without the need for
    inline CSS/JavaScript.

    Needs FakeChoicesMixin for the fake choices the template will be using (the
    upstream implementation depends on inline JavaScript for this, which we
    want to avoid).
    """

    template = 'admin/amo/numeric_range_filter.html'

    def choices(self, changelist):
        # We want a fake 'All' choice as per FakeChoicesMixin, but as of 0.3.15
        # rangefilter's implementation doesn't bother setting the selected
        # property, and our mixin calls super(), so we have to do it here.
        all_choice = next(super().choices(changelist))
        all_choice['selected'] = not any(self.used_parameters)
        yield all_choice


class MultipleRelatedListFilter(admin.SimpleListFilter):
    template = 'admin/amo/multiple_filter.html'

    def __init__(self, request, params, *args, **kwargs):
        # Django's implementation builds self.used_parameters by pop()ing keys
        # from params, so we would normally only get a single value.
        # We want the full list if a parameter is passed twice, to allow
        # multiple values to be selected, so we build our own _used_parameters
        # property from request.GET ourselves, using .getlist() to get all the
        # values.
        self._used_parameters = {}
        if self.parameter_name in params:
            self._used_parameters[self.parameter_name] = (
                request.GET.getlist(self.parameter_name) or None
            )
        super().__init__(request, params, *args, **kwargs)
        # We copy our self._used_parameters in the real property so it's
        # available in the rest of the code (for things called from
        # super().__init__(), it's too late, they'll need to be overriden and
        # use our property with the underscore if they want to benefit from
        # that improvement).
        self.used_parameters = self._used_parameters

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            selected = (
                lookup is None if self.value() is None else str(lookup) in self.value()
            )
            yield {
                'selected': selected,
                'value': lookup,
                'display': title,
                # Django doesn't give the template access to the changelist
                # instance. For its own filter classes, it builds a link for
                # each choice from the changelist querystring, passing that
                # here. In our case we have a form so we need to render an
                # hidden input for each parameter in the query string. We help
                # the template do that by passing a QueryDict instead of the
                # raw query string like MultipleRelatedListFilter does.
                'params': QueryDict(
                    cl.get_query_string(remove=[self.parameter_name])[1:]
                ),
            }


class MultiSelectFieldListFilter(admin.FieldListFilter):
    """Allows multiple fields to be selected in a list filter.
    Returns objects with any of the selected filters.
    """

    def expected_parameters(self):
        return [self.lookup_kwarg]

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.lookup_kwarg = field_path + '__in'

        super().__init__(field, request, params, model, model_admin, field_path)

        # If none are selected, reset
        self.lookup_val = self.used_parameters.get(self.lookup_kwarg, [])
        if self.lookup_val == ['']:
            self.lookup_val = []

        self.empty_value_display = model_admin.get_empty_value_display()
        parent_model, _ = reverse_field_path(model, field_path)
        queryset = (
            model_admin.get_queryset(request)
            if model == parent_model
            else parent_model._default_manager.all()
        )

        self.lookup_choices = queryset.distinct().values_list(field.name, flat=True)

    def choices(self, changelist):
        yield {
            'selected': not self.lookup_val,
            'query_string': changelist.get_query_string(remove=[self.lookup_kwarg]),
            'display': 'All',
        }

        for choice in self.lookup_choices:
            choice = str(choice)
            selected_values = (
                [value for value in self.lookup_val if value != choice]
                if choice in self.lookup_val
                else self.lookup_val + [choice]
            )

            if selected_values:
                yield {
                    'selected': choice in self.lookup_val,
                    'query_string': changelist.get_query_string(
                        {self.lookup_kwarg: ','.join(selected_values)}
                    ),
                    'display': choice,
                }
            else:
                yield {
                    'selected': choice in self.lookup_val,
                    'query_string': changelist.get_query_string(
                        remove=[self.lookup_kwarg]
                    ),
                    'display': choice,
                }


class ExclusiveMultiSelectFieldListFilter(MultiSelectFieldListFilter):
    """An exclusive version of MultiSelectFieldListFilter.
    An object must be part of all selected filters to be returned.
    """

    def queryset(self, request, queryset):
        if self.lookup_val:
            for val in self.lookup_val:
                queryset = queryset.filter(**{self.field_path: val})
        return queryset
