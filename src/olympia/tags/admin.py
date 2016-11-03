from django.contrib import admin

from .models import Tag


class TagAdmin(admin.ModelAdmin):
    list_display = ('tag_text', 'popularity', 'created', 'denied')
    list_editable = ('denied',)
    list_filter = ('denied',)
    ordering = ('-created',)
    search_fields = ('^tag_text',)


admin.site.register(Tag, TagAdmin)
