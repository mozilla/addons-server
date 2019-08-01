from django.contrib import admin

from .models import PrimaryHero


class PrimaryHeroInline(admin.StackedInline):
    model = PrimaryHero
    fields = ('image', 'gradient_color', 'enabled')
    view_on_site = False
