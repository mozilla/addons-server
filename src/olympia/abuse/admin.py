from django.contrib import admin
from django.db.models import Q

from .models import AbuseReport


class AbuseReportTypeFilter(admin.SimpleListFilter):
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
        return (('user', 'Users'), ('addon', 'Addons'))

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'user':
            return queryset.filter(user__isnull=False)
        elif self.value() == 'addon':
            return queryset.filter(
                Q(addon__isnull=False) | Q(guid__isnull=False)
            )
        return queryset


class AbuseReportAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon', 'user', 'reporter')
    readonly_fields = (
        'ip_address',
        'message',
        'created',
        'addon',
        'user',
        'guid',
        'reporter',
    )
    list_display = (
        'reporter',
        'ip_address',
        'type',
        'target',
        'message',
        'created',
    )
    list_filter = (AbuseReportTypeFilter,)
    actions = ('delete_selected',)


admin.site.register(AbuseReport, AbuseReportAdmin)
