from django.contrib import admin
from django.db.models import Prefetch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.admin import (
    AMOModelAdmin,
    DateRangeFilter,
    MultipleRelatedListFilter,
)
from olympia.translations.utils import truncate_text
from olympia.zadmin.admin import related_single_content_link

from .models import Rating


class RatingTypeFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = 'Type'

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
            ('rating', 'User Rating'),
            ('reply', 'Developer/Admin Reply'),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'rating':
            return queryset.filter(reply_to__isnull=True)
        elif self.value() == 'reply':
            return queryset.filter(reply_to__isnull=False)
        return queryset


class AddonFilterForIPSearch(MultipleRelatedListFilter):
    """Filter for `addon`, only available on IP search as it's expensive."""

    title = 'By Addon'
    parameter_name = 'addon'

    def lookups(self, request, model_admin):
        # This filter needs to find all addon ids from the main queryset, which
        # causes it to be expensive, so only do that if we're doing an IP
        # search. If the IP search is cancelled or changed though, the user
        # might end up with an add-on filter still active that no longer
        # matches, so we support filter values that are already present in the
        # querystring, allowing the user to remove them.
        lookups = {
            int(addon_id): '??'
            for addon_id in self._used_parameters.get(self.parameter_name, [])
        }
        if (
            search_term := model_admin.get_search_query(request)
        ) and model_admin.ip_addresses_and_networks_from_query(search_term):
            qs, search_use_distinct = model_admin.get_search_results(
                request, model_admin.get_queryset(request), search_term
            )
            lookups_from_queryset = dict(
                qs.values_list('addon', 'addon__guid').distinct().order_by('addon_id')
            )
            lookups.update(lookups_from_queryset)
        return [
            (addon_id, f'{addon_id}: {addon_guid}')
            for addon_id, addon_guid in lookups.items()
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value is None:
            return queryset
        return queryset.filter(addon__in=value)


class RatingAdmin(AMOModelAdmin):
    raw_id_fields = (
        'addon',
        'version',
        'user',
        'reply_to',
    )
    readonly_fields = (
        'addon',
        'addon_link',
        'version',
        'user',
        'reply_to',
        'known_ip_adresses',
        'body',
        'rating',
        'deleted',
        'user_link',
    )
    fields = (
        'addon_link',
        'version',
        'body',
        'rating',
        'known_ip_adresses',
        'user_link',
        'deleted',
    )
    list_display = (
        'id',
        'addon',
        'created',
        'user',
        'known_ip_adresses',
        'rating',
        'is_reply',
        'flag',
        'deleted',
        'truncated_body',
    )
    list_filter = (
        'deleted',
        RatingTypeFilter,
        'rating',
        ('created', DateRangeFilter),
        AddonFilterForIPSearch,
    )
    actions = ('delete_selected',)
    list_select_related = ('user',)  # For addon/reply_to see get_queryset()
    search_fields = ('body',)
    extra_list_display_for_ip_searches = ()
    search_by_ip_actions = (
        amo.LOG.ADD_RATING.id,
        amo.LOG.EDIT_RATING.id,
    )
    search_by_ip_activity_accessor = 'ratinglog__activity_log'
    search_by_ip_activity_reverse_accessor = 'activity_log__ratinglog__rating'

    def get_search_id_field(self, request):
        # Numeric searches are by add-on for ratings (the rating id rarely
        # matters, it's more important to be able to search by add-on id).
        return 'addon'

    def get_queryset(self, request):
        base_qs = Rating.unfiltered.all()
        return base_qs.prefetch_related(
            Prefetch('addon', queryset=Addon.unfiltered.all().only_translations()),
            Prefetch('reply_to', queryset=base_qs),
        )

    def has_add_permission(self, request):
        return False

    def truncated_body(self, obj):
        return truncate_text(obj.body, 140)[0] if obj.body else ''

    def is_reply(self, obj):
        return bool(obj.reply_to)

    is_reply.boolean = True
    is_reply.admin_order_field = 'reply_to'

    def addon_link(self, obj):
        return related_single_content_link(obj, 'addon')

    addon_link.short_description = 'Add-on'

    def user_link(self, obj):
        return related_single_content_link(obj, 'user')

    user_link.short_description = 'User'


admin.site.register(Rating, RatingAdmin)
