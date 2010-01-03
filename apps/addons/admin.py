from django import forms
from django.contrib import admin

from .models import Addon, BlacklistedGuid, Feature


class AddonForm(forms.ModelForm):

    class Meta:
        model = Addon

    def clean(self):
        # Override clean so we ignore uniqueness checks on the django side,
        # since they don't handle translations correctly.
        return self.cleaned_data


class AddonAdmin(admin.ModelAdmin):
    form = AddonForm
    raw_id_fields = ('users',)

    fieldsets = (
        (None, {
            'fields': ('name', 'guid', 'defaultlocale', 'addontype', 'status',
                       'higheststatus', 'users', 'nominationdate'),
        }),
        ('Details', {
            'fields': ('summary', 'description', 'homepage', 'eula',
                       'privacypolicy', 'developercomments', 'icontype',
                       'the_reason', 'the_future'),
        }),
        ('Support', {
            'fields': ('supporturl', 'supportemail',
                       'get_satisfaction_company', 'get_satisfaction_product'),
        }),
        ('Stats', {
            'fields': ('averagerating', 'bayesianrating', 'totalreviews',
                       'weeklydownloads', 'totaldownloads',
                       'average_daily_downloads', 'average_daily_users',
                       'sharecount'),
        }),
        ('Truthiness', {
            'fields': ('inactive', 'trusted', 'viewsource', 'publicstats',
                       'prerelease', 'adminreview', 'sitespecific',
                       'externalsoftware', 'binary', 'dev_agreement',
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


admin.site.register(BlacklistedGuid)
admin.site.register(Feature, FeatureAdmin)
admin.site.register(Addon, AddonAdmin)
