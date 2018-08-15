from django.contrib import admin

from .models import AkismetReport


class AkismetAdmin(admin.ModelAdmin):
    readonly_fields = ('rating_instance',)


admin.site.register(AkismetReport, AkismetAdmin)
