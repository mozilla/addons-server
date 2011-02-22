from django.contrib import admin

from .models import File


class FileAdmin(admin.ModelAdmin):
    raw_id_fields = ('version',)


admin.site.register(File, FileAdmin)
