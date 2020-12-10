from django.conf import settings
from django.contrib import admin
from django.db.models import Prefetch
from django.forms.models import modelformset_factory
from django.utils.html import format_html

from olympia.addons.models import Addon
from olympia.hero.admin import PrimaryHeroInline
from olympia.versions.models import Version

from .forms import AdminBasePromotedApprovalFormSet
from .models import PromotedApproval, PromotedSubscription


class PromotedApprovalInlineChecks(admin.checks.InlineModelAdminChecks):
    def _check_relation(self, obj, parent_model):
        """PromotedApproval doesn't have a direct FK to PromotedAddon (it's via
        Addon, Version) so we have to bypass this check.
        """
        return []


class PromotedSubscriptionInline(admin.StackedInline):
    model = PromotedSubscription
    view_on_site = False
    extra = 0  # No extra form should be added...
    max_num = 1  # ...and we expect up to one form.
    fields = (
        'onboarding_rate',
        'onboarding_period',
        'onboarding_url',
        'link_visited_at',
        'checkout_cancelled_at',
        'checkout_completed_at',
        'cancelled_at',
        'stripe_information',
    )
    readonly_fields = (
        'onboarding_url',
        'link_visited_at',
        'checkout_cancelled_at',
        'checkout_completed_at',
        'cancelled_at',
        'stripe_information',
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = self.readonly_fields
        onboarding_fields = ('onboarding_rate', 'onboarding_period')

        if (
            obj
            and hasattr(obj, 'promotedsubscription')
            and obj.promotedsubscription.stripe_checkout_completed
        ):
            readonly_fields = onboarding_fields + readonly_fields
        return readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def onboarding_url(self, obj):
        return format_html('<pre>{}</pre>', obj.get_onboarding_url())

    onboarding_url.short_description = 'Onboarding URL'

    def stripe_information(self, obj):
        if not obj or not obj.stripe_subscription_id:
            return '-'

        stripe_sub_url = '/'.join(
            [settings.STRIPE_DASHBOARD_URL, 'subscriptions', obj.stripe_subscription_id]
        )

        return format_html(
            '<a href="{}">View subscription on Stripe</a>', stripe_sub_url
        )

    stripe_information.short_description = 'Stripe information'


class PromotedApprovalInline(admin.TabularInline):
    model = PromotedApproval
    extra = 0
    max_num = 0
    fields = ('version', 'group_id', 'application_id')
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
        qs = qs.filter(version__addon__promotedaddon=self.instance).order_by(
            '-version_id'
        )
        return qs


class PromotedAddonAdmin(admin.ModelAdmin):
    list_display = (
        'addon__name',
        'group_id',
        'application_id',
        'is_approved',
        'primary_hero_shelf',
    )
    view_on_site = False
    raw_id_fields = ('addon',)
    fields = ('addon', 'group_id', 'application_id')
    list_filter = ('group_id', 'application_id')
    inlines = (PromotedApprovalInline, PrimaryHeroInline, PromotedSubscriptionInline)

    class Media:
        js = ('js/admin/promotedaddon.js',)

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
            .select_related('primaryhero')
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

    def addon__name(self, obj):
        return str(obj.addon)

    addon__name.short_description = 'Addon'

    def is_approved(self, obj):
        apps = obj.approved_applications
        if not apps:
            return False
        elif apps == obj.all_applications:
            return True
        else:
            # return None when there are some apps approved but not all.
            return None

    is_approved.boolean = True

    def primary_hero_shelf(self, obj):
        return obj.primaryhero.enabled if hasattr(obj, 'primaryhero') else None

    primary_hero_shelf.boolean = True

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        from olympia.discovery.admin import SlugOrPkChoiceField

        if db_field.name == 'addon':
            kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(
                db_field.remote_field, self.admin_site, using=kwargs.get('using')
            )
            kwargs['queryset'] = Addon.objects.all()
            kwargs['help_text'] = db_field.help_text
            return SlugOrPkChoiceField(**kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        qs = PrimaryHeroInline.model.objects.filter(enabled=True)
        shelf = getattr(obj, 'primaryhero', None)
        if shelf and shelf.enabled and qs.count() == 1:
            return False
        return super().has_delete_permission(request=request, obj=obj)
