import functools

from django.contrib import admin
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import (
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.template import loader
from django.urls import re_path, reverse
from django.utils.html import format_html, format_html_join

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.admin import AMOModelAdmin, DateRangeFilter, FakeChoicesMixin
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.ratings.models import Rating
from olympia.translations.utils import truncate_text

from .models import AbuseReport, CinderPolicy, ContentDecision
from .tasks import sync_cinder_policies


class AbuseReportTypeFilter(admin.SimpleListFilter):
    # Human-readable title to be displayed in the sidebar just above the filter options.
    title = 'type'

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
            ('user', 'Users'),
            ('collection', 'Collections'),
            ('rating', 'Ratings'),
            ('addon', 'Add-ons'),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'user':
            return queryset.filter(user__isnull=False)
        elif self.value() == 'collection':
            return queryset.filter(collection__isnull=False)
        elif self.value() == 'rating':
            return queryset.filter(rating__isnull=False)
        elif self.value() == 'addon':
            return queryset.filter(guid__isnull=False)
        return queryset


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
    title = 'minimum reports count (grouped by guid)'
    parameter_name = 'minimum_reports_count'

    def lookups(self, request, model_admin):
        """
        Fake lookups() method required to show the filter.
        """
        return ((),)

    def queryset(self, request, queryset):
        return queryset


class AbuseReportAdmin(AMOModelAdmin):
    class Media:
        css = {'all': (vite_asset('css/admin-abuse-report.less'),)}

    date_hierarchy = 'modified'
    list_display = (
        'target_name',
        'guid',
        'type',
        'distribution',
        'reason',
        'message_excerpt',
        'created',
    )
    list_filter = (
        AbuseReportTypeFilter,
        'reason',
        ('created', DateRangeFilter),
        MinimumReportsCountFilter,
    )
    list_select_related = ('user', 'collection', 'rating')
    # Shouldn't be needed because those fields should all be readonly, but just
    # in case we change our mind, FKs should be raw id fields as usual in our
    # admin tools.
    raw_id_fields = ('user', 'collection', 'rating', 'reporter')
    # All fields must be readonly - the submitted data should not be changed.
    readonly_fields = (
        'created',
        'modified',
        'reporter',
        'reporter_name',
        'reporter_email',
        'country_code',
        'guid',
        'user',
        'collection',
        'rating',
        'message',
        'client_id',
        'addon_name',
        'addon_summary',
        'addon_version',
        'addon_signature',
        'application',
        'application_version',
        'application_locale',
        'operating_system',
        'operating_system_version',
        'install_date',
        'addon_install_origin',
        'addon_install_method',
        'addon_install_source',
        'addon_install_source_url',
        'report_entry_point',
        'addon_card',
        'location',
        'illegal_category',
        'illegal_subcategory',
        'reason',
    )
    fieldsets = (
        ('Abuse Report Core Information', {'fields': ('reason', 'message')}),
        (
            'Abuse Report Data',
            {
                'fields': (
                    'created',
                    'modified',
                    'reporter',
                    'reporter_name',
                    'reporter_email',
                    'country_code',
                    'client_id',
                    'addon_signature',
                    'application',
                    'application_version',
                    'application_locale',
                    'operating_system',
                    'operating_system_version',
                    'install_date',
                    'addon_install_origin',
                    'addon_install_method',
                    'addon_install_source',
                    'addon_install_source_url',
                    'report_entry_point',
                    'location',
                    'illegal_category',
                    'illegal_subcategory',
                )
            },
        ),
    )
    # The first fieldset is going to be dynamically added through
    # get_fieldsets() depending on the target (add-on, user, rating, collection,
    # or unknown add-on), using the fields below:
    dynamic_fieldset_fields = {
        # User
        'user': (('User', {'fields': ('user',)}),),
        # Collection
        'collection': (('Collection', {'fields': ('collection',)}),),
        # Rating
        'rating': (('Rating', {'fields': ('rating',)}),),
        # Add-on, we only have the guid and maybe some extra addon_*
        # fields that were submitted with the report, we'll try to display the
        # addon card if we can find a matching add-on in the database though.
        'guid': (
            ('Add-on', {'fields': ('addon_card',)}),
            (
                'Submitted Info',
                {'fields': ('addon_name', 'addon_version', 'guid', 'addon_summary')},
            ),
        ),
    }
    view_on_site = False  # Abuse reports have no public page to link to.

    def has_add_permission(self, request):
        # Adding new abuse reports through the admin is useless, so we prevent it.
        return False

    def has_delete_permission(self, request, obj=None):
        # Abuse reports shouldn't be deleted, only resolved
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_continue'] = False  # Don't need this.
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def get_search_fields(self, request):
        """
        Return search fields according to the type filter.
        """
        type_ = request.GET.get('type')
        if type_ == 'addon':
            search_fields = (
                'addon_name',
                'guid__startswith',
                'message',
            )
        elif type_ == 'user':
            search_fields = (
                'message',
                'user__id',
                'user__email__like',
            )
        elif type_ == 'collection':
            search_fields = (
                'message',
                'collection__slug',
            )
        elif type_ == 'rating':
            search_fields = (
                'message',
                'rating__id',
                'rating__body__like',
            )
        else:
            search_fields = ()
        return search_fields

    def get_search_id_field(self, request):
        """
        Return the field to use when all search terms are numeric, according to
        the type filter.
        """
        return (
            f'{request_type}_id'
            if request
            and (request_type := request.GET.get('type'))
            and request_type in ('user', 'rating', 'collection')
            else None
        )

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
            guids = (
                qs.values_list('guid', flat=True)
                .filter(guid__isnull=False)
                .annotate(Count('guid'))
                .filter(guid__count__gte=minimum_reports_count)
                .order_by()
            )
            qs = qs.filter(guid__in=list(guids))
        qs, use_distinct = super().get_search_results(request, qs, search_term)
        return qs, use_distinct

    def get_fieldsets(self, request, obj=None):
        if obj.user:
            target = 'user'
        elif obj.collection:
            target = 'collection'
        elif obj.rating:
            target = 'rating'
        else:
            target = 'guid'
        return self.dynamic_fieldset_fields[target] + self.fieldsets

    def target_name(self, obj):
        name = obj.user.name if obj.user else obj.addon_name
        return '{} {}'.format(name, obj.addon_version or '')

    target_name.short_description = 'User / Add-on'

    def addon_card(self, obj):
        # Note: this assumes we don't allow guids to be reused by developers
        # when deleting add-ons. That used to be true, so for historical data
        # it may not be the right add-on (for those cases, we don't know for
        # sure what the right add-on is).
        if not obj.guid:
            return ''
        try:
            addon = Addon.unfiltered.get(guid=obj.guid)
        except Addon.DoesNotExist:
            return ''

        template = loader.get_template('reviewers/addon_details_box.html')
        try:
            approvals_info = addon.addonapprovalscounter
        except AddonApprovalsCounter.DoesNotExist:
            approvals_info = None

        # Provide all the necessary context addon_details_box.html needs. Note
        # the use of Paginator() to match what the template expects.
        context = {
            'addon': addon,
            'addon_name': addon.name,
            'amo': amo,
            'approvals_info': approvals_info,
            'reports': Paginator(
                AbuseReport.objects.all().for_addon(addon).exclude(pk=obj.pk), 5
            ).page(1),
            'user_ratings': Paginator(
                (
                    Rating.without_replies.filter(
                        addon=addon, rating__lte=3, body__isnull=False
                    ).order_by('-created')
                ),
                5,
            ).page(1),
            'version': addon.current_version,
        }
        return template.render(context)

    addon_card.short_description = ''

    def distribution(self, obj):
        return obj.get_addon_signature_display() if obj.addon_signature else ''

    distribution.short_description = 'Distribution'

    def reporter_country(self, obj):
        return obj.country_code

    reporter_country.short_description = "Reporter's country"

    def message_excerpt(self, obj):
        return truncate_text(obj.message, 140)[0] if obj.message else ''

    message_excerpt.short_description = 'Message excerpt'


class CinderPolicyAdmin(AMOModelAdmin):
    fields = (
        'id',
        'created',
        'modified',
        'uuid',
        'parent',
        'name',
        'text',
        'expose_in_reviewer_tools',
        'present_in_cinder',
    )
    list_display = (
        'uuid',
        'parent',
        'name',
        'linked_review_reasons',
        'expose_in_reviewer_tools',
        'present_in_cinder',
        'enforcement_actions',
        'text',
    )
    readonly_fields = tuple(set(fields) - {'expose_in_reviewer_tools'})
    ordering = ('parent__name', 'name')
    list_select_related = ('parent',)
    view_on_site = False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(ordering='reviewactionreason__name')
    def linked_review_reasons(self, obj):
        review_reasons = [
            (
                reverse('admin:reviewers_reviewactionreason_change', args=(reason.pk,)),
                reason,
            )
            for reason in obj.reviewactionreason_set.all()
        ]

        return format_html(
            '<ul>{}</ul>',
            format_html_join('\n', '<li><a href="{}">{}</a></li>', review_reasons),
        )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('reviewactionreason_set')

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return functools.update_wrapper(wrapper, view)

        urlpatterns = super().get_urls()
        custom_urlpatterns = [
            re_path(
                r'^sync_cinder_policies/$',
                wrap(self.sync_cinder_policies),
                name='abuse_sync_cinder_policies',
            ),
        ]
        return custom_urlpatterns + urlpatterns

    def sync_cinder_policies(self, request, extra_context=None):
        if not acl.action_allowed_for(request.user, amo.permissions.ADMIN_ADVANCED):
            return HttpResponseForbidden()

        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        sync_cinder_policies.delay()
        self.message_user(request, 'Cinder policies sync task triggered.')
        return HttpResponseRedirect(reverse('admin:abuse_cinderpolicy_changelist'))


class ContentDecisionAdmin(AMOModelAdmin):
    fields = (
        'id',
        'created',
        'modified',
        'addon',
        'user',
        'rating',
        'collection',
        'action',
        'action_date',
        'cinder_id',
        'reasoning',
        'private_notes',
        'policies',
        'appeal_job',
    )
    list_display = (
        'created',
        'action',
        'addon',
        'user',
        'rating',
        'collection',
    )
    readonly_fields = fields
    view_on_site = False

    def has_add_permission(self, request):
        # Adding new decisions through the admin is useless, so we prevent it.
        return False

    def has_delete_permission(self, request, obj=None):
        # Decisions shouldn't be deleted - if they're wrong, they should be overridden.
        return False

    def has_change_permission(self, request, obj=None):
        # Decisions can't be changed - if they're wrong, they should be overridden.
        return False


admin.site.register(AbuseReport, AbuseReportAdmin)
admin.site.register(CinderPolicy, CinderPolicyAdmin)
admin.site.register(ContentDecision, ContentDecisionAdmin)
