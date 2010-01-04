from django.contrib import admin

from .models import Application, AppVersion


class AppVersionAdmin(admin.StackedInline):
    model = AppVersion
    ordering = ('-version_int',)


class ApplicationAdmin(admin.ModelAdmin):
    inlines = [AppVersionAdmin]


admin.site.register(Application, ApplicationAdmin)
