from django.contrib import admin
from django.db.models import Prefetch
from django.forms.models import modelformset_factory

from olympia.addons.models import Addon
from olympia.discovery.admin import SlugOrPkChoiceField
from olympia.hero.admin import PrimaryHeroInline
from olympia.versions.models import Version

from .forms import AdminBasePromotedApprovalFormSet
from .models import PromotedAddon, PromotedApproval


class PromotedApprovalInlineChecks(admin.checks.InlineModelAdminChecks):
    def _check_relation(self, obj, parent_model):
        """PromotedApproval doesn't have a direct FK to PromotedAddon (it's via
        Addon, Version) so we have to bypass this check.
        """
        return []


class PromotedApprovalInline(admin.TabularInline):
    model = PromotedApproval
    extra = 0
    max_num = 0
    fields = ('version', 'group_id')
    can_delete = True
    view_on_site = False
    checks_class = PromotedApprovalInlineChecks

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_formset(self, request, obj=None, **kwargs):
        self.instance = obj
        Formset = modelformset_factory(
            self.model,
            fields=self.fields,
            formset=AdminBasePromotedApprovalFormSet,
            extra=self.get_extra(request, obj, **kwargs),
            min_num=self.get_min_num(request, obj, **kwargs),
            max_num=self.get_max_num(request, obj, **kwargs),
            can_delete=self.can_delete,
        )
        return Formset

    def get_queryset(self, request):
        # TODO: implement pagination like FileInline does

        qs = super().get_queryset(request)
        qs = (
            qs.filter(version__addon__promotedaddon=self.instance)
              .order_by('-version_id'))
        return qs


@admin.register(PromotedAddon)
class PromotedAddonAdmin(admin.ModelAdmin):
    list_display = (
        'addon__name', 'group_id', 'application_id', 'is_approved',
        'primary_hero_shelf')
    view_on_site = False
    raw_id_fields = ('addon',)
    fields = ('addon', 'group_id', 'application_id')
    list_filter = ('group_id', 'application_id')
    inlines = (PromotedApprovalInline, PrimaryHeroInline)

    @classmethod
    def _transformer(self, objs):
        Version.transformer_promoted(
            [promo.addon._current_version for promo in objs]
        )

    def get_queryset(self, request):
        # Select `primaryhero`, `addon` and it's `_current_version`.
        # We are forced to use `prefetch_related` to ensure transforms
        # are being run, though, we only care about translations
        qset = (
            self.model.objects.all()
            .select_related('primaryhero')
            .prefetch_related(
                Prefetch(
                    'addon',
                    queryset=(
                        Addon.unfiltered.all()
                        .select_related('_current_version')
                        .only_translations())))
            .transform(self._transformer))
        return qset

    def addon__name(self, obj):
        return str(obj.addon)
    addon__name.short_description = 'Addon'

    def is_approved(self, obj):
        return obj.is_addon_currently_promoted
    is_approved.boolean = True

    def primary_hero_shelf(self, obj):
        return (obj.primaryhero.enabled if hasattr(obj, 'primaryhero')
                else None)
    primary_hero_shelf.boolean = True

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name == 'addon':
            kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(
                db_field.remote_field, self.admin_site,
                using=kwargs.get('using'))
            kwargs['queryset'] = Addon.objects.all()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        return super().formfield_for_foreignkey(
            db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        qs = PrimaryHeroInline.model.objects.filter(enabled=True)
        shelf = getattr(obj, 'primaryhero', None)
        if shelf and shelf.enabled and qs.count() == 1:
            return False
        return super().has_delete_permission(request=request, obj=obj)
