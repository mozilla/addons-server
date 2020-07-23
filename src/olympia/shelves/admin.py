from django.contrib import admin
from .forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'shelf_type')
    actions = ['delete_selected']
    form = ShelfForm
