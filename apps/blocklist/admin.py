from django.contrib import admin

from . import forms
from . import models


class PluginAdmin(admin.ModelAdmin):
    form = forms.BlocklistPluginForm


ms = models.BlocklistItem, models.BlocklistPlugin, models.BlocklistGfx
inlines = [type(cls.__name__ + 'Inline', (admin.StackedInline,),
                {'model': cls})
           for cls in ms]


class DetailAdmin(admin.ModelAdmin):
    inlines = inlines


admin.site.register(models.BlocklistApp)
admin.site.register(models.BlocklistCA)
admin.site.register(models.BlocklistItem)
admin.site.register(models.BlocklistPlugin, PluginAdmin)
admin.site.register(models.BlocklistGfx)
admin.site.register(models.BlocklistDetail, DetailAdmin)
