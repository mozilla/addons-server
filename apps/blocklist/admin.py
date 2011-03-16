from django.contrib import admin

from . import models


ms = models.BlocklistItem, models.BlocklistPlugin, models.BlocklistGfx
inlines = [type(cls.__name__ + 'Inline', (admin.StackedInline,),
                {'model': cls})
           for cls in ms]


class DetailAdmin(admin.ModelAdmin):
    inlines = inlines

admin.site.register(models.BlocklistApp)
admin.site.register(models.BlocklistItem)
admin.site.register(models.BlocklistPlugin)
admin.site.register(models.BlocklistGfx)
admin.site.register(models.BlocklistDetail, DetailAdmin)
