from django.contrib import admin

from olympia.shelves.forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'position', 'enabled')
    list_editable = ('position', 'enabled')
    actions = ['delete_selected']
    form = ShelfForm
    ordering = ('position',)
