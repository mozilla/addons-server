from django.contrib import admin
from django.db.models import Prefetch
from django.forms.models import modelformset_factory

from olympia.addons.models import Addon
from olympia.amo.admin import AMOModelAdmin
from olympia.hero.models import PrimaryHero

from .forms import AdminBasePromotedApprovalFormSet
from .models import PromotedAddon, PromotedApproval, PromotedGroup


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
    fields = ('version', 'promoted_group', 'application_id')
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
        if not self.instance:
            return self.model.objects.none()
        qs = super().get_queryset(request)
        qs = qs.filter(version__addon=self.instance).order_by('-version_id')
        return qs


class PromotedAddonAdminInline(admin.TabularInline):
    model = PromotedAddon
    extra = 0
    view_on_site = False
    raw_id_fields = ('addon',)
    fields = ('addon', 'promoted_group', 'application_id')
    select_related = ('promoted_group',)

    def get_queryset(self, request):
        # Select `primaryhero`, `addon` and it's `_current_version`.
        # We are forced to use `prefetch_related` to ensure transforms
        # are being run, though, we only care about translations
        qset = self.model.objects.all().prefetch_related(
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
        from olympia.discovery.admin import SlugOrPkChoiceField

        if db_field.name == 'addon':
            kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(
                db_field.remote_field, self.admin_site, using=kwargs.get('using')
            )
            kwargs['queryset'] = Addon.objects.all()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        if db_field.name == 'promoted_group':
            kwargs['queryset'] = PromotedGroup.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        addon = getattr(obj, 'addon', None)
        qs = PrimaryHero.objects.filter(addon=addon, enabled=True)
        shelf = getattr(obj, 'primaryhero', None)
        if shelf and shelf.enabled and qs.count() == 1:
            return False
        return super().has_delete_permission(request=request, obj=obj)


class PromotedGroupAdmin(AMOModelAdmin):
    model = PromotedGroup
    list_display = [
        'name',
        'listed_pre_review',
        'unlisted_pre_review',
        'admin_review',
        'badged',
        'can_primary_hero',
        'flag_for_human_review',
        'can_be_compatible_with_all_fenix_versions',
        'high_profile',
        'high_profile_rating',
        'search_ranking_bump',
        'active',
    ]
    list_filter = list_display
    search_fields = ('name',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
