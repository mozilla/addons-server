from django.contrib import admin

from .models import Addon, BlacklistedGuid, Feature, Category


class AddonAdmin(admin.ModelAdmin):
    exclude = ('authors',)
    list_display = ('__unicode__', 'type', 'status', 'average_rating')
    list_filter = ('type', 'status')

    fieldsets = (
        (None, {
            'fields': ('name', 'guid', 'default_locale', 'type', 'status',
                       'highest_status', 'nomination_date'),
        }),
        ('Details', {
            'fields': ('summary', 'description', 'homepage', 'eula',
                       'privacy_policy', 'developer_comments', 'icon_type',
                       'the_reason', 'the_future'),
        }),
        ('Support', {
            'fields': ('support_url', 'support_email',
                       'get_satisfaction_company', 'get_satisfaction_product'),
        }),
        ('Stats', {
            'fields': ('average_rating', 'bayesian_rating', 'total_reviews',
                       'weekly_downloads', 'total_downloads',
                       'average_daily_downloads', 'average_daily_users',
                       'share_count'),
        }),
        ('Truthiness', {
            'fields': ('inactive', 'trusted', 'view_source', 'public_stats',
                       'prerelease', 'admin_review', 'site_specific',
                       'external_software', 'binary', 'dev_agreement',
                       'show_beta'),
        }),
        ('Money', {
            'fields': ('wants_contributions', 'paypal_id', 'suggested_amount',
                       'annoying'),
        }),
        ('Dictionaries', {
            'fields': ('target_locale', 'locale_disambiguation'),
        }))


class FeatureAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)
    list_filter = ('application', 'locale')
    list_display = ('addon', 'application', 'locale')


class CategoryAdmin(admin.ModelAdmin):
    raw_id_fields = ('addons',)
    list_display = ('name', 'application', 'type', 'count')
    list_filter = ('application', 'type')


admin.site.register(BlacklistedGuid)
admin.site.register(Feature, FeatureAdmin)
admin.site.register(Addon, AddonAdmin)
admin.site.register(Category, CategoryAdmin)
