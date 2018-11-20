from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import ugettext_lazy as _
from django.urls import reverse

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


class RatingAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon', 'version', 'user', 'reply_to',)
    readonly_fields = ('addon', 'addon_link', 'version', 'user', 'reply_to',
                       'ip_address', 'body', 'rating', 'deleted',
                       'ip_address_link', 'user_link')
    fields = ('addon_link', 'version', 'body', 'rating', 'ip_address_link',
              'user_link', 'deleted')
    list_display = ('id', 'addon', 'truncated_body', 'rating', 'user',
                    'ip_address', 'flag', 'is_reply', 'deleted',)
    list_filter = ('deleted', RatingTypeFilter)
    actions = ('delete_selected',)

    def queryset(self, request):
        return Rating.unfiltered.all()

    def truncated_body(self, obj):
        return truncate_text(obj.body, 140)[0]

    def is_reply(self, obj):
        return bool(obj.reply_to)
    is_reply.boolean = True
    is_reply.admin_order_field = 'reply_to'

    def addon_link(self, obj):
        return related_single_content_link(obj, 'addon')
    addon_link.short_description = _(u'Add-on')

    def user_link(self, obj):
        return related_single_content_link(obj, 'user')
    user_link.short_description = _(u'User')

    def ip_address_link(self, obj):
        return format_html(
            '<a href="{}?{}={}">{}</a>',
            reverse('admin:ratings_rating_changelist'),
            'ip_address', obj.ip_address, obj.ip_address)
    ip_address_link.short_description = _(u'IP Address')


admin.site.register(Rating, RatingAdmin)
