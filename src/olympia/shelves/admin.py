from django.contrib import admin


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'shelf_type')
    actions = ['delete_selected']
