from django.contrib import admin

from . import forms
from . import models


def stacked_inline(model):
    return type(model.__name__ + 'Inline', (admin.StackedInline,),
                {'model': model})


class PluginAdmin(admin.ModelAdmin):
    form = forms.BlocklistPluginForm


class AppAdmin(admin.ModelAdmin):
    form = forms.BlocklistAppForm


# TODO: The prefs should be inlined in the detail edit form as well,
# and/or the detail edit form should be inlined here. Django does
# not make either of these things easy.
class ItemAdmin(admin.ModelAdmin):
    inlines = stacked_inline(models.BlocklistPref),


ms = (models.BlocklistItem, models.BlocklistPlugin, models.BlocklistGfx,
      models.BlocklistIssuerCert)
inlines = map(stacked_inline, ms)


class DetailAdmin(admin.ModelAdmin):
    inlines = inlines


admin.site.register(models.BlocklistApp, AppAdmin)
admin.site.register(models.BlocklistCA)
admin.site.register(models.BlocklistItem, ItemAdmin)
admin.site.register(models.BlocklistPlugin, PluginAdmin)
admin.site.register(models.BlocklistGfx)
admin.site.register(models.BlocklistIssuerCert)
admin.site.register(models.BlocklistDetail, DetailAdmin)
