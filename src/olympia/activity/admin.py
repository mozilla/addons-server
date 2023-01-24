from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin
from olympia.reviewers.models import ReviewActionReason
from olympia.zadmin.admin import related_single_content_link

from .models import ActivityLog, ReviewActionReasonLog


class ActivityLogAdmin(AMOModelAdmin):
    list_display = (
        'created',
        'user_link',
        'pretty_arguments',
    )
    raw_id_fields = ('user',)
    readonly_fields = (
        'created',
        'user',
        'pretty_arguments',
    )
    date_hierarchy = 'created'
    fields = (
        'user',
        'created',
        'pretty_arguments',
    )
    raw_id_fields = ('user',)
    view_on_site = False

    def lookup_allowed(self, lookup, value):
        if lookup == 'addonlog__addon':
            return True
        return super().lookup_allowed(lookup, value)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def pretty_arguments(self, obj):
        return obj.to_string(type_='admin')

    def user_link(self, obj):
        return related_single_content_link(obj, 'user')

    user_link.short_description = 'User'


class ReviewActionReasonLogAdmin(AMOModelAdmin):
    date_hierarchy = 'created'
    fields = (
        'created',
        'activity_log',
        'activity_log__user__email',
        'reason',
    )
    list_display = (
        'created',
        'activity_log',
        'reason',
        'activity_log__user__email',
    )
    list_filter = ('reason',)
    list_select_related = ('activity_log__user',)
    readonly_fields = (
        'created',
        'activity_log',
        'activity_log__user__email',
    )
    search_fields = ('activity_log__user__email',)
    view_on_site = False

    def activity_log__user__email(self, obj):
        return obj.activity_log.user.email

    def has_add_permission(self, request):
        return False

    def get_form(self, request, obj=None, **kwargs):
        form = super(ReviewActionReasonLogAdmin, self).get_form(request, obj, **kwargs)
        form.base_fields['reason'].widget.can_add_related = False
        form.base_fields['reason'].widget.can_change_related = False
        form.base_fields['reason'].empty_label = None
        form.base_fields['reason'].choices = [
            (reason.id, reason.labelled_name())
            for reason in ReviewActionReason.objects.all()
        ]
        return form


admin.site.register(ActivityLog, ActivityLogAdmin)
admin.site.register(ReviewActionReasonLog, ReviewActionReasonLogAdmin)
