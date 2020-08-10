from django.contrib import admin

from .forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', )
    actions = ['delete_selected']
    form = ShelfForm


class ShelfManagementAdmin(admin.ModelAdmin):
    list_display = ('position', 'shelf', 'enabled')
    list_display_links = ('shelf',)
    list_editable = ('position', 'enabled')
    actions = ['delete_selected']
    ordering = [F('position').asc(nulls_last=True)]
