from django.contrib import admin

from .models import Collection


class CollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'addon_count', 'downloads')
    list_filter = ('type', 'listed')
    fields = ('name', 'slug', 'uuid', 'listed', 'type', 'application',
              'default_locale', 'author')
    raw_id_fields = ('author',)
    readonly_fields = ('name', 'uuid')


admin.site.register(Collection, CollectionAdmin)
