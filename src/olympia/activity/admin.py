from django.contrib import admin

from .models import ActivityLog, ReviewActionReasonLog
from olympia.reviewers.models import ReviewActionReason


class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        'created',
        'user',
        '__str__',
    )
    raw_id_fields = ('user',)
    readonly_fields = (
        'created',
        'user',
        '__str__',
    )
    date_hierarchy = 'created'
    fields = (
        'user',
        'created',
        '__str__',
    )
    raw_id_fields = ('user',)
    view_on_site = False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReviewActionReasonLogAdmin(admin.ModelAdmin):
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
