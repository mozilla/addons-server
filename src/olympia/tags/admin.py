from django.contrib import admin

from .models import Tag


class TagAdmin(admin.ModelAdmin):
    list_display = ('tag_text', 'popularity', 'created', 'blacklisted')
    list_editable = ('blacklisted',)
    list_filter = ('blacklisted',)
    ordering = ('-created',)
    search_fields = ('^tag_text',)


admin.site.register(Tag, TagAdmin)
