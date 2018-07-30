from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import ForeignKeyRawIdWidget
from django.db.models import Q
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


class PositionFilter(admin.SimpleListFilter):
    # Title for the filter section.
    title = 'presence in Disco Pane editorial content'

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'position'

    # Database field to use.
    db_field = 'position'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples.
        # - The first element in each tuple is the coded value for the option
        #   that will appear in the URL query.
        # - The second element is the human-readable name for the option that
        #   will appear
        in the right sidebar.
        """
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value provided in the query
        string and retrievable via `self.value()`.
        """
        # Compare the requested value (either 'on' or 'off')
        # to decide how to filter the queryset.
        if self.value() == 'yes':
            return queryset.filter(**{self.db_field + '__gt': 0})
        if self.value() == 'no':
            return queryset.filter(
                Q(**{self.db_field: 0}) | Q(**{self.db_field: None}))


class PositionChinaFilter(PositionFilter):
    title = 'presence in Disco Pane editorial content (China edition)'
    parameter_name = 'position_china'
    db_field = 'position'


class DiscoveryItemAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/discovery.css',)
        }
    list_display = ('__unicode__', 'custom_addon_name', 'custom_heading',
                    'position', 'position_china')
    list_filter = (PositionFilter, PositionChinaFilter)
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

    def build_preview(self, obj, locale):
        return format_html(
            u'<div class="discovery-preview" data-locale="{}">'
            u'<h2 class="heading">{}</h2>'
            u'<div class="editorial-description">{}</div></div>',
            locale,
            mark_safe(obj.heading),
            mark_safe(obj.description))

    def previews(self, obj):
        translations = []
        for locale in ('en-US', ) + KEY_LOCALES_FOR_EDITORIAL_CONTENT:
            with translation.override(locale):
                translations.append(self.build_preview(obj, locale))
        return format_html(u''.join(translations))


admin.site.register(DiscoveryItem, DiscoveryItemAdmin)
