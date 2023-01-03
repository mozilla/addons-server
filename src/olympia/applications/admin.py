from django.contrib import admin

from olympia.amo.admin import AMOModelAdmin

from .models import AppVersion


class AppVersionAdmin(AMOModelAdmin):
    list_display = (
        'version',
        'application',
    )
    model = AppVersion
    ordering = ('-version_int',)


admin.site.register(AppVersion, AppVersionAdmin)
