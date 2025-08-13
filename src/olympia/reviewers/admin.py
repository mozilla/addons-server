from urllib.parse import urljoin

from django import forms
from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from olympia import amo
from olympia.amo.admin import AMOModelAdmin
from olympia.zadmin.admin import related_single_content_link

from .models import NeedsHumanReview, ReviewActionReason, ReviewQueueHistory, UsageTier


class ReviewActionReasonAdminForm(forms.ModelForm):
    def clean(self):
        is_active = self.cleaned_data.get('is_active', False)
        if is_active and not self.cleaned_data.get('cinder_policy'):
            msg = forms.ValidationError(
                self.fields['cinder_policy'].error_messages['required']
            )
            self.add_error('cinder_policy', msg)
        return self.cleaned_data


class ReviewActionReasonAdmin(AMOModelAdmin):
    form = ReviewActionReasonAdminForm
    list_display = (
        'name',
        'linked_cinder_policy',
        'addon_type',
        'is_active',
    )
    list_filter = (
        'addon_type',
        'is_active',
    )
    fields = (
        'name',
        'is_active',
        'canned_response',
        'canned_block_reason',
        'addon_type',
        'cinder_policy',
    )
    raw_id_fields = ('cinder_policy',)
    view_on_site = False
    list_select_related = ('cinder_policy', 'cinder_policy__parent')

    def linked_cinder_policy(self, obj):
        return related_single_content_link(obj, 'cinder_policy')


admin.site.register(ReviewActionReason, ReviewActionReasonAdmin)


class UsageTierAdmin(AMOModelAdmin):
    list_display = (
        'slug',
        'name',
        'lower_adu_threshold',
        'upper_adu_threshold',
    )
    view_on_site = False
    fields = (
        'slug',
        'name',
        'lower_adu_threshold',
        'upper_adu_threshold',
        'growth_threshold_before_flagging',
        'computed_growth_threshold_before_flagging',
        'computed_number_of_addons_that_would_be_flagged_for_growth',
        'abuse_reports_ratio_threshold_before_flagging',
        'computed_number_of_addons_that_would_be_flagged_for_abuse_reports',
        'ratings_ratio_threshold_before_flagging',
        'computed_number_of_addons_that_would_be_flagged_for_ratings',
        'abuse_reports_ratio_threshold_before_disabling',
        'computed_number_of_addons_that_would_be_disabled_for_abuse_reports',
        'ratings_ratio_threshold_before_disabling',
        'computed_number_of_addons_that_would_be_disabled_for_ratings',
    )
    readonly_fields = (
        'computed_growth_threshold_before_flagging',
        'computed_number_of_addons_that_would_be_flagged_for_growth',
        'computed_number_of_addons_that_would_be_flagged_for_abuse_reports',
        'computed_number_of_addons_that_would_be_flagged_for_ratings',
        'computed_number_of_addons_that_would_be_disabled_for_abuse_reports',
        'computed_number_of_addons_that_would_be_disabled_for_ratings',
    )

    def computed_growth_threshold_before_flagging(self, obj):
        return obj.get_growth_threshold()

    def computed_number_of_addons_that_would_be_flagged_for_growth(self, obj):
        return (
            (
                UsageTier.get_base_addons()
                .filter(obj.get_growth_threshold_q_object())
                .count()
            )
            if obj.growth_threshold_before_flagging
            else 0
        )

    def computed_number_of_addons_that_would_be_flagged_for_abuse_reports(self, obj):
        return (
            (
                UsageTier.get_base_addons()
                .alias(abuse_reports_count=UsageTier.get_abuse_count_subquery())
                .filter(obj.get_abuse_threshold_q_object(disable=False))
                .count()
            )
            if obj.abuse_reports_ratio_threshold_before_flagging
            else 0
        )

    def computed_number_of_addons_that_would_be_disabled_for_abuse_reports(self, obj):
        return (
            (
                UsageTier.get_base_addons()
                .alias(abuse_reports_count=UsageTier.get_abuse_count_subquery())
                .filter(obj.get_abuse_threshold_q_object(disable=True))
                .count()
            )
            if obj.abuse_reports_ratio_threshold_before_disabling
            else 0
        )

    def computed_number_of_addons_that_would_be_flagged_for_ratings(self, obj):
        return (
            (
                UsageTier.get_base_addons()
                .alias(ratings_count=UsageTier.get_rating_count_subquery())
                .filter(obj.get_rating_threshold_q_object(disable=False))
                .count()
            )
            if obj.ratings_ratio_threshold_before_flagging
            else 0
        )

    def computed_number_of_addons_that_would_be_disabled_for_ratings(self, obj):
        return (
            (
                UsageTier.get_base_addons()
                .alias(ratings_count=UsageTier.get_rating_count_subquery())
                .filter(obj.get_rating_threshold_q_object(disable=True))
                .count()
            )
            if obj.ratings_ratio_threshold_before_disabling
            else 0
        )

    def get_form(self, request, obj=None, **kwargs):
        if obj:
            help_texts = {
                'computed_growth_threshold_before_flagging': (
                    'Actual growth threshold above which we would flag add-ons in that '
                    'tier, as computed using the percentage defined above and the '
                    'current average growth of add-ons (currently {}) in that tier.'
                ).format(obj.average_growth),
                'computed_number_of_addons_that_would_be_flagged_for_growth': (
                    'Number of add-ons that would be flagged for growth using the '
                    'percentage defined above, if the task ran now with the current '
                    'add-on growth values.'
                ),
            }
            kwargs.update({'help_texts': help_texts})
        return super().get_form(request, obj, **kwargs)


admin.site.register(UsageTier, UsageTierAdmin)


class NeedsHumanReviewAdmin(AMOModelAdmin):
    list_display = ('addon_guid', 'version', 'created', 'reason', 'is_active')
    list_filter = ('is_active',)
    raw_id_fields = ('version',)
    view_on_site = False
    list_select_related = ('version', 'version__addon')
    fields = ('created', 'modified', 'reason', 'version', 'is_active')
    readonly_fields = ('reason', 'created', 'modified')
    list_filter = (
        'reason',
        'is_active',
        'created',
    )

    actions = ['deactivate_selected', 'activate_selected']

    def deactivate_selected(modeladmin, request, queryset):
        for obj in queryset:
            # This will also trigger <Version>.reset_due_date(), which will
            # clear the due date if it's no longer needed.
            obj.update(is_active=False)

    def activate_selected(modeladmin, request, queryset):
        for obj in queryset:
            # This will also trigger <Version>.reset_due_date(), which will
            # set the due date if there wasn't one.
            obj.update(is_active=True)

    def addon_guid(self, obj):
        return obj.version.addon.guid


admin.site.register(NeedsHumanReview, NeedsHumanReviewAdmin)


class ReviewQueueHistoryAdmin(AMOModelAdmin):
    list_display = (
        'id',
        'version',
        'created',
        'original_due_date',
        'exit_date',
        'review_decision_log',
        'review_link',
    )
    view_on_site = False

    def review_link(self, obj):
        version = obj.version
        return format_html(
            '<a href="{}">Review</a>',
            urljoin(
                settings.EXTERNAL_SITE_URL,
                reverse(
                    'reviewers.review',
                    args=[
                        'unlisted'
                        if version.channel == amo.CHANNEL_UNLISTED
                        else 'listed',
                        version.addon_id,
                    ],
                ),
            ),
        )

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ReviewQueueHistory, ReviewQueueHistoryAdmin)
