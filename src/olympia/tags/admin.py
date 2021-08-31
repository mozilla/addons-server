from django.contrib import admin

from .models import Tag


class TagAdmin(admin.ModelAdmin):
    list_display = ('tag_text', 'num_addons', 'created', 'enable_for_random_shelf')
    ordering = ('-created',)
    search_fields = ('^tag_text',)
    readonly_fields = ('num_addons', 'created')
    list_editable = ('enable_for_random_shelf',)


admin.site.register(Tag, TagAdmin)
