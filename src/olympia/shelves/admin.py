from django.contrib import admin

from .forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', )
    actions = ['delete_selected']
    form = ShelfForm
