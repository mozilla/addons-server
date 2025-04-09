from django.contrib import admin
from django.db.models import Prefetch, Q
from django.forms.models import modelformset_factory

from olympia.addons.models import Addon
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.hero.models import PrimaryHero
from olympia.versions.models import Version

from .forms import AdminBasePromotedApprovalFormSet
from .models import PromotedAddonPromotion, PromotedAddonVersion, PromotedGroup


class PromotedAddonVersionInlineChecks(admin.checks.InlineModelAdminChecks):
    def _check_relation(self, obj, parent_model):
        """PromotedAddonVersion doesn't have a direct FK to PromotedAddon (it's via
        Addon, Version) so we have to bypass this check.
        """
        return []


class PromotedAddonVersionInline(admin.TabularInline):
    model = PromotedAddonVersion
    extra = 0
    max_num = 0
    fields = ('version', 'promoted_group', 'application_id')
    can_delete = True
    view_on_site = False
    checks_class = PromotedAddonVersionInlineChecks

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
        if not self.instance:
            return self.model.objects.none()
        qs = super().get_queryset(request)
        qs = qs.filter(version__addon=self.instance).order_by('-version_id')
        return qs


class PromotedAddonPromotionAdminInline(admin.TabularInline):
    model = PromotedAddonPromotion
    extra = 0
    view_on_site = False
    raw_id_fields = ('addon',)
    fields = ('addon', 'promoted_group', 'application_id')
    select_related = ('promoted_group',)

    @classmethod
    def _transformer(self, objs):
        Version.transformer_promoted(
            [
                promo.addon._current_version
                for promo in objs
                if promo.addon._current_version
            ]
        )

    def get_queryset(self, request):
        # Select `primaryhero`, `addon` and it's `_current_version`.
        # We are forced to use `prefetch_related` to ensure transforms
        # are being run, though, we only care about translations
        qset = (
            self.model.objects.all()
            .prefetch_related(
                Prefetch(
                    'addon',
                    queryset=(
                        Addon.unfiltered.all()
                        .select_related('_current_version')
                        .only_translations()
                    ),
                )
            )
            .transform(self._transformer)
        )
        return qset

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        from olympia.discovery.admin import SlugOrPkChoiceField

        if db_field.name == 'addon':
            kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(
                db_field.remote_field, self.admin_site, using=kwargs.get('using')
            )
            kwargs['queryset'] = Addon.objects.all()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        if db_field.name == 'promoted_group':
            kwargs['queryset'] = PromotedGroup.objects.filter(
                ~Q(group_id=PROMOTED_GROUP_CHOICES.NOT_PROMOTED)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        addon = getattr(obj, 'addon', None)
        qs = PrimaryHero.objects.filter(addon=addon, enabled=True)
        shelf = getattr(obj, 'primaryhero', None)
        if shelf and shelf.enabled and qs.count() == 1:
            return False
        return super().has_delete_permission(request=request, obj=obj)
