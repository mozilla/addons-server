from django.contrib import admin
from piston.models import Consumer


class ConsumerAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'secret', 'status', 'user')
    raw_id_fields = ('user',)

admin.site.register(Consumer, ConsumerAdmin)
