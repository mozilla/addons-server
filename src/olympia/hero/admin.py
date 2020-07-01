import os
import tempfile

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet
from django.utils.safestring import mark_safe

from olympia.amo.utils import resize_image

from PIL import Image

from .models import (
    PrimaryHero, SecondaryHeroModule,
    PrimaryHeroImage)


class ImageChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return mark_safe(
            '<img class="select-image-preview" src="{}" />'.format(
                obj.preview_url))


class PrimaryHeroInline(admin.StackedInline):
    class Media:
        css = {
            'all': ('css/admin/discovery.css',)
        }
    model = PrimaryHero
    fields = (
        'image',
        'select_image',
        'gradient_color',
        'is_external',
        'enabled')
    view_on_site = False
    can_delete = False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'select_image':
            kwargs['required'] = False
            kwargs['widget'] = forms.RadioSelect(attrs={
                'class': 'inline',
                'style': 'vertical-align: top'
            })
            kwargs['queryset'] = PrimaryHeroImage.objects
            kwargs['empty_label'] = mark_safe("""
                <div class="select-image-noimage">
                    No image selected
                </div>
                """)
            return ImageChoiceField(**kwargs)
        return super().formfield_for_foreignkey(
            db_field, request, **kwargs)


class PrimaryHeroImageAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/discovery.css',)
        }
    list_display = ('preview_image', 'custom_image')
    actions = ['delete_selected']
    readonly_fields = ('preview_image',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        (path, fn) = os.path.split(obj.custom_image.path)
        dest_thumb = path + b'/thumbs/' + fn

        size_thumb = (150, 120)
        size_full = (960, 640)

        img = Image.open(obj.custom_image)
        f = tempfile.NamedTemporaryFile(dir=settings.TMP_PATH)
        img.save(f, 'png')

        resize_image(f.name, dest_thumb, size_thumb)
        resize_image(f.name, obj.custom_image.path, size_full)


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
