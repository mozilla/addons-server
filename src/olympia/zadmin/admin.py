from django.contrib import admin
from piston.models import Consumer

from . import models


class ConsumerAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'secret', 'status', 'user')
    raw_id_fields = ('user',)

admin.site.register(models.Config)
admin.site.register(Consumer, ConsumerAdmin)
admin.site.disable_action('delete_selected')

admin.site.register(models.DownloadSource)
