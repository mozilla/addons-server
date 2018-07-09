from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import ForeignKeyRawIdWidget

from olympia.addons.models import Addon
from olympia.discovery.models import DiscoveryItem


class SlugOrPkChoiceField(forms.ModelChoiceField):
    """A ModelChoiceField that supports entering slugs instead of PKs for
    convenience."""
    def clean(self, value):
        if value and isinstance(value, basestring) and not value.isdigit():
            try:
                value = self.queryset.values_list(
                    'pk', flat=True).get(slug=value)
            except self.queryset.model.DoesNotExist:
                value = value
        return super(SlugOrPkChoiceField, self).clean(value)


class DiscoveryItemAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/larger_raw_id.css',)
        }
    raw_id_fields = ('addon',)
    list_display = ('__unicode__', 'custom_addon_name', 'custom_heading',)
    view_on_site = False

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name == 'addon':
            kwargs['widget'] = ForeignKeyRawIdWidget(
                db_field.rel, self.admin_site, using=kwargs.get('using'))
            kwargs['queryset'] = Addon.objects.public()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        return super(DiscoveryItemAdmin, self).formfield_for_foreignkey(
            db_field, request, **kwargs)


admin.site.register(DiscoveryItem, DiscoveryItemAdmin)
