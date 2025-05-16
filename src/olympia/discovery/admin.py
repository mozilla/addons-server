from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import ForeignKeyRawIdWidget
from django.db.models import Prefetch
from django.utils import translation
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext

from olympia import amo, promoted
from olympia.addons.models import Addon
from olympia.amo.admin import AMOModelAdmin, ExclusiveMultiSelectFieldListFilter
from olympia.amo.reverse import reverse
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.discovery.models import DiscoveryItem
from olympia.hero.admin import (
    PrimaryHeroImageAdmin,
    PrimaryHeroInline,
    SecondaryHeroAdmin,
)
from olympia.hero.models import PrimaryHeroImage, SecondaryHero
from olympia.promoted.admin import (
    PromotedAddonAdminInline,
    PromotedApprovalInline,
    PromotedGroupAdmin,
)
from olympia.promoted.models import PromotedGroup
from olympia.shelves.admin import ShelfAdmin
from olympia.shelves.models import Shelf


# Popular locales, we typically don't want to show a string if it's not
# translated in those.
KEY_LOCALES_FOR_EDITORIAL_CONTENT = ('de', 'fr', 'es-ES', 'pl', 'it', 'ja')


class SlugOrPkChoiceField(forms.ModelChoiceField):
    """A ModelChoiceField that supports entering slugs instead of PKs for
    convenience."""

    def clean(self, value):
        if value and isinstance(value, str) and not value.isdigit():
            try:
                value = self.queryset.values_list('pk', flat=True).get(slug=value)
            except self.queryset.model.DoesNotExist:
                value = value
        return super().clean(value)


class PositionFilter(admin.SimpleListFilter):
    # Title for the filter section.
    title = 'presence in Disco Pane editorial content'

    # Parameter for the filter that will be used in the URL query. It's also
    # the name of the database field.
    parameter_name = 'position'

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
            return queryset.filter(**{self.parameter_name + '__gt': 0})
        if self.value() == 'no':
            return queryset.filter(**{self.parameter_name: 0})


class PositionChinaFilter(PositionFilter):
    title = 'presence in Disco Pane editorial content (China edition)'
    parameter_name = 'position_china'


class DiscoveryItemAdmin(AMOModelAdmin):
    class Media:
        css = {'all': (vite_asset('css/admin-discovery.less'),)}

    list_display = (
        '__str__',
        'position',
        'position_china',
    )
    list_filter = (PositionFilter, PositionChinaFilter)
    raw_id_fields = ('addon',)
    readonly_fields = ('previews',)
    view_on_site = False

    def get_queryset(self, request):
        # Select `addon` as well as it's `_current_version`.
        # We are forced to use `prefetch_related` to ensure transforms
        # are being run, though, we only care about translations
        qset = DiscoveryItem.objects.all().prefetch_related(
            Prefetch(
                'addon',
                queryset=(
                    Addon.unfiltered.all()
                    .select_related('_current_version')
                    .only_translations()
                ),
            )
        )
        return qset

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name == 'addon':
            kwargs['widget'] = ForeignKeyRawIdWidget(
                db_field.remote_field, self.admin_site, using=kwargs.get('using')
            )
            kwargs['queryset'] = Addon.objects.all()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def build_preview(self, obj, locale):
        return format_html(
            '<div class="discovery-preview" data-locale="{}">'
            '<h2 class="heading">{}</h2>'
            '<div class="editorial-description">{}</div></div>',
            locale,
            obj.addon.name,
            mark_safe(
                gettext(obj.custom_description) or obj.addon_summary_fallback or ''
            ),
        )

    def previews(self, obj):
        translations = []
        for locale in ('en-US',) + KEY_LOCALES_FOR_EDITORIAL_CONTENT:
            with translation.override(locale):
                translations.append(conditional_escape(self.build_preview(obj, locale)))
        return mark_safe(''.join(translations))


class PromotedAddon(promoted.models.PromotedAddon):
    """Just a proxy class to have all the hero related objects in one
    place under Discovery in django admin."""

    class Meta:
        proxy = True


class PrimaryHeroImageUpload(PrimaryHeroImage):
    """Just a proxy class to have all the hero related objects in one
    place under Discovery in django admin."""

    class Meta:
        proxy = True
        verbose_name_plural = 'primary hero images'


class SecondaryHeroShelf(SecondaryHero):
    """Just a proxy class to have all the hero shelf related objects in one
    place under Discovery in django admin."""

    class Meta(SecondaryHero.Meta):
        proxy = True
        verbose_name_plural = 'secondary hero shelves'


class HomepageShelves(Shelf):
    class Meta:
        proxy = True
        verbose_name_plural = 'homepage shelves'


class DiscoveryAddon(Addon):
    class Meta:
        proxy = True


class DiscoveryPromotedGroup(PromotedGroup):
    class Meta:
        proxy = True


class AddonPromotionFilter(admin.SimpleListFilter):
    title = 'Promotion'
    parameter_name = 'promotion'

    def lookups(self, request, model_admin):
        return [
            ('promoted', 'Promoted'),
            ('not_promoted', 'Not Promoted'),
        ]

    def queryset(self, request, queryset):
        is_null = self.value() != 'promoted'
        if self.value():
            return queryset.filter(promotedaddon__isnull=is_null)


class AddonPromotedGroupFilter(ExclusiveMultiSelectFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'promoted group'


class AddonApprovalFilter(ExclusiveMultiSelectFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = 'approval'


class AddonPromotionApplicationFilter(admin.SimpleListFilter):
    title = 'Application'
    parameter_name = 'application'

    def lookups(self, request, model_admin):
        return [
            (amo.ANDROID.id, amo.ANDROID.pretty),
            (amo.FIREFOX.id, amo.FIREFOX.pretty),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(promotedaddon__application_id=self.value())


DISCOVERY_ADDON_FIELDS = ['__str__', 'guid', 'addon', 'is_promoted']


class DiscoveryAddonAdmin(AMOModelAdmin):
    model = DiscoveryAddon
    inlines = [
        PromotedAddonAdminInline,
        PromotedApprovalInline,
        PrimaryHeroInline,
    ]
    fields = DISCOVERY_ADDON_FIELDS
    readonly_fields = DISCOVERY_ADDON_FIELDS
    list_display = [field for field in DISCOVERY_ADDON_FIELDS if field != 'addon']
    search_fields = (
        'slug__startswith',
        'guid__startswith',
    )
    list_filter = (
        AddonPromotionFilter,
        ('promotedaddon__promoted_group__name', AddonPromotedGroupFilter),
        (
            '_current_version__promoted_versions__promoted_group__name',
            AddonApprovalFilter,
        ),
        'type',
        AddonPromotionApplicationFilter,
    )

    def get_queryset(self, request):
        qset = Addon.unfiltered.all().only_translations()
        return qset

    def addon(self, obj):
        if obj.pk:
            return format_html(
                '<a href="{}">{}</a>',
                reverse('admin:addons_addon_change', args=[obj.pk]),
                'addon',
            )
        return '-'

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def is_promoted(self, obj):
        return obj.is_promoted

    is_promoted.boolean = True


admin.site.register(DiscoveryAddon, DiscoveryAddonAdmin)
admin.site.register(DiscoveryPromotedGroup, PromotedGroupAdmin)
admin.site.register(DiscoveryItem, DiscoveryItemAdmin)
admin.site.register(PrimaryHeroImageUpload, PrimaryHeroImageAdmin)
admin.site.register(SecondaryHeroShelf, SecondaryHeroAdmin)
admin.site.register(HomepageShelves, ShelfAdmin)
