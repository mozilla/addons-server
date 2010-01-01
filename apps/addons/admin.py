from django import forms
from django.contrib import admin

from .models import Addon, BlacklistedGuid


class AddonForm(forms.ModelForm):

    class Meta:
        model = Addon

    def clean(self):
        return self.cleaned_data


class AddonAdmin(admin.ModelAdmin):
    form = AddonForm
    raw_id_fields = ('users',)


admin.site.register(BlacklistedGuid)
admin.site.register(Addon, AddonAdmin)
