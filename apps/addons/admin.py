from django import forms
from django.contrib import admin

from .models import Addon, BlacklistedGuid, Feature


class AddonForm(forms.ModelForm):

    class Meta:
        model = Addon

    def clean(self):
        return self.cleaned_data


class AddonAdmin(admin.ModelAdmin):
    form = AddonForm
    raw_id_fields = ('users',)


class FeatureAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)
    list_filter = ('application', 'locale')


admin.site.register(BlacklistedGuid)
admin.site.register(Feature, FeatureAdmin)
admin.site.register(Addon, AddonAdmin)
