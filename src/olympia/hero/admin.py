from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet

from .models import PrimaryHero, SecondaryHeroModule


class PrimaryHeroInline(admin.StackedInline):
    model = PrimaryHero
    fields = (
        'image',
        'custom_image',
        'gradient_color',
        'is_external',
        'enabled')
    view_on_site = False
    can_delete = False


class HeroModuleInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if len(self.forms) != 3:
            raise ValidationError(
                'There must be exactly 3 modules in this shelf.')


class SecondaryHeroModuleInline(admin.StackedInline):
    model = SecondaryHeroModule
    view_on_site = False
    max_num = 3
    min_num = 3
    can_delete = False
    formset = HeroModuleInlineFormSet


class SecondaryHeroAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/discovery.css',)
        }
    list_display = ('headline', 'description', 'enabled')
    inlines = [SecondaryHeroModuleInline]
    view_on_site = False

    def has_delete_permission(self, request, obj=None):
        qs = self.get_queryset(request).filter(enabled=True)
        if obj and list(qs) == [obj]:
            return False
        return super().has_delete_permission(request=request, obj=obj)
