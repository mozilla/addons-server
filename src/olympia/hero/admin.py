from django.contrib import admin

from .models import PrimaryHero


class PrimaryHeroAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'disco_addon', 'enabled',)
    view_on_site = False


admin.site.register(PrimaryHero, PrimaryHeroAdmin)
