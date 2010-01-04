from django.contrib import admin

from .models import CannedResponse


class CannedResponseAdmin(admin.ModelAdmin):
    list_display = ('name', 'response')


admin.site.register(CannedResponse, CannedResponseAdmin)
