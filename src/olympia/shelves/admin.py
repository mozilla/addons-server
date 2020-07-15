from django.contrib import admin


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'shelfType')
    actions = ['delete_selected']
