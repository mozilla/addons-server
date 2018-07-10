from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import ForeignKeyRawIdWidget
from django.utils import translation
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from olympia.addons.models import Addon
from olympia.discovery.models import DiscoveryItem


# Popular locales, we typically don't want to show a string if it's not
# translated in those.
KEY_LOCALES_FOR_EDITORIAL_CONTENT = ('de', 'fr', 'es', 'pl', 'it', 'ja')


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
            'all': ('css/admin/discovery.css',)
        }
    list_display = ('__unicode__', 'custom_addon_name', 'custom_heading',)
    raw_id_fields = ('addon',)
    readonly_fields = ('previews',)
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

    def build_preview(self, obj):
        return format_html(
            u'<br/><h2 class="heading">{}</h2>'
            u'<div class="editorial-description">{}</div>',
            mark_safe(obj.heading),
            mark_safe(obj.description))

    def previews(self, obj):
        translations = []
        for locale in ('en-US', ) + KEY_LOCALES_FOR_EDITORIAL_CONTENT:
            with translation.override(locale):
                translations.append(self.build_preview(obj))
        return format_html(u''.join(translations))


admin.site.register(DiscoveryItem, DiscoveryItemAdmin)
